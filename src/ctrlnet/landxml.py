"""LandXML 1.2 米制 GPS 子集；CgPoint 文本顺序 north/east/elev。

本模块的 ECEF profile 以 Y/X/Z 写 CgPoint，GPSVector 始终为 ECEF。
Feature/Property 保存 ctrlnet 元数据，不支持的地面观测显式拒绝导出。
"""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

import numpy as np

from .gnss import GnssPoint, GnssBaseline, GnssNetwork, GnssCovarianceBlock

NS = 'http://www.landxml.org/schema/LandXML-1.2'
ET.register_namespace('', NS)


def _tag(name):
    return f'{{{NS}}}{name}'


def _feature(parent, **values):
    f = ET.SubElement(parent, _tag('Feature'), code='ctrlnet')
    for key, value in values.items():
        ET.SubElement(f, _tag('Property'), label=key, value=json.dumps(value, ensure_ascii=False))


def _metadata(parent):
    return {p.attrib['label']: json.loads(p.attrib['value'])
            for f in parent.findall(_tag('Feature')) if f.get('code') == 'ctrlnet'
            for p in f.findall(_tag('Property'))}


def export_landxml(network: GnssNetwork, path):
    """导出 ECEF GPS 子集到文件，返回 Path；ENU 基线旋转为 ECEF。"""
    if network.distances or network.angles or network.leveling or network.geoid is not None:
        raise ValueError('LandXML GPS 子集不支持地面观测或 geoid')
    network._validate_covariance_blocks()
    root = ET.Element(_tag('LandXML'), version='1.2', date='2000-01-01', time='00:00:00')
    units = ET.SubElement(root, _tag('Units'))
    ET.SubElement(units, _tag('Metric'), linearUnit='meter', areaUnit='squareMeter',
                  volumeUnit='cubicMeter', temperatureUnit='celsius', pressureUnit='milliBars',
                  angularUnit='decimal degrees', directionUnit='decimal degrees')
    survey = ET.SubElement(root, _tag('Survey'))
    ET.SubElement(survey, _tag('SurveyHeader'), name=network.name)
    points = ET.SubElement(survey, _tag('CgPoints'))
    setups = {}
    for i, p in enumerate(network.points):
        node = ET.SubElement(points, _tag('CgPoint'), name=p.name)
        x, y, z = p.ecef
        node.text = f'{y:.17g} {x:.17g} {z:.17g}'
        setups[p.name] = f'gps_{i}'
        ET.SubElement(survey, _tag('GPSSetup'), id=setups[p.name], stationName=p.name, antennaHeight='0')
    for b in network.baselines:
        delta, cov = b.ecef_observation(network._by_name)
        node = ET.SubElement(survey, _tag('GPSVector'), setupID_A=setups[b.frm],
                             setupID_B=setups[b.to], **dict(zip(('dX', 'dY', 'dZ'), map(str, delta))))
        ET.SubElement(node, _tag('TargetPoint'), pntRef=b.to)
        _feature(node, covariance=cov.tolist())
    # Rotate the entire session, including its cross terms.
    from .gnss import ecef_to_enu_matrix
    sessions = []
    for block in network.covariance_blocks:
        n = len(block.indices) * 3
        t = np.zeros((n, n))
        for j, i in enumerate(block.indices):
            b = network.baselines[i]
            p = network.point(b.reference)
            t[3*j:3*j+3, 3*j:3*j+3] = (np.eye(3) if b.frame == 'ECEF' else
                                                      ecef_to_enu_matrix(p.lat, p.lon).T)
        sessions.append(dict(indices=list(block.indices), covariance=(t @ block.covariance @ t.T).tolist(), name=block.name))
    _feature(survey, coordinate_frame='ECEF', fixed=[p.name for p in network.fixed_points],
             origin=network.origin, parameter_frame=network.parameter_frame, sessions=sessions)
    path = Path(path)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)
    return path


def import_landxml(path, *, coordinate_frame=None, default_sigma=None):
    """读 GPSSetup/GPSVector/CgPoints。外部文件需明确 ECEF，缺 VCV 需给 σ(m)。

    非零天线高需要外部归心，本子集拒绝静默使用；不进行投影或单位猜测。
    """
    root = ET.parse(path).getroot()
    if root.tag != _tag('LandXML') or root.get('version') != '1.2':
        raise ValueError('需要 LandXML 1.2 命名空间和版本')
    metric = root.find('./' + _tag('Units') + '/' + _tag('Metric'))
    if metric is None or metric.get('linearUnit') != 'meter':
        raise ValueError('仅支持米制 LandXML')
    surveys = root.findall(_tag('Survey'))
    if len(surveys) > 1:
        raise ValueError('仅支持一个 Survey')
    survey = surveys[0] if surveys else root
    meta = _metadata(survey)
    if (coordinate_frame or meta.get('coordinate_frame')) != 'ECEF':
        raise ValueError('必须明确 coordinate_frame="ECEF"；不支持投影坐标')
    points = []
    for node in root.iter(_tag('CgPoint')):
        values = np.asarray([float(v) for v in (node.text or '').split()])
        if values.shape != (3,):
            raise ValueError('CgPoint 需要 north east elev 三分量')
        y, x, z = values
        points.append(GnssPoint.from_ecef(node.attrib['name'], [x, y, z],
                                         fixed=node.attrib['name'] in meta.get('fixed', [])))
    setups = {}
    for node in survey.iter(_tag('GPSSetup')):
        key = node.attrib['id']
        if key in setups:
            raise ValueError('GPSSetup id 重复')
        if float(node.attrib['antennaHeight']) != 0:
            raise ValueError('仅支持已归心的零天线高 GPSSetup')
        setups[key] = node.attrib['stationName']
    baselines = []
    for node in survey.iter(_tag('GPSVector')):
        cov = _metadata(node).get('covariance')
        if cov is None:
            if default_sigma is None or not np.isfinite(default_sigma) or default_sigma <= 0:
                raise ValueError('缺少 VCV：请提供正的 default_sigma（米）')
            cov = np.eye(3) * default_sigma**2
        baselines.append(GnssBaseline(setups[node.attrib['setupID_A']], setups[node.attrib['setupID_B']],
                                      [float(node.attrib[k]) for k in ('dX', 'dY', 'dZ')], cov))
    unsupported = ('GPSPosition', 'RawObservation', 'ReducedObservation', 'InstrumentSetup')
    if any(list(survey.iter(_tag(tag))) for tag in unsupported):
        raise ValueError('存在 GPS 子集以外的测站观测')
    header = survey.find(_tag('SurveyHeader'))
    return GnssNetwork(points, baselines, origin=meta.get('origin'),
                       parameter_frame=meta.get('parameter_frame', 'ECEF'),
                       name=header.get('name', 'landxml') if header is not None else 'landxml',
                       covariance_blocks=[GnssCovarianceBlock(**b) for b in meta.get('sessions', [])])


read_landxml = import_landxml
write_landxml = export_landxml
