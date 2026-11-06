import xml.etree.ElementTree as ET
import numpy as np
import pytest
from ctrlnet import solve_gnss
from ctrlnet.landxml import export_landxml, import_landxml, NS
from test_gnss_corr import correlated_network


@pytest.mark.parametrize('frame', ['ECEF', 'ENU'])
def test_roundtrip(tmp_path, frame):
    net, _ = correlated_network(frame)
    net.name = '测站 & GPS'
    path = export_landxml(net, tmp_path/'survey.xml')
    other = import_landxml(path)
    assert other.name == net.name
    assert other.point_names == net.point_names
    assert [p.fixed for p in other.points] == [p.fixed for p in net.points]
    for a, b in zip(net.baselines, other.baselines):
        np.testing.assert_allclose(a.ecef_observation(net._by_name)[0], b.delta, atol=1e-12)
    np.testing.assert_allclose(solve_gnss(other).Cx, solve_gnss(net).Cx, atol=1e-17)
    assert other.covariance_blocks[0].name == 'epoch1'


def test_external_subset_and_errors(tmp_path):
    path = tmp_path/'external.xml'
    path.write_text(f'''<LandXML xmlns="{NS}" version="1.2"><Units><Metric linearUnit="meter"/></Units>
    <CgPoints><CgPoint name="A">0 6378137 0</CgPoint><CgPoint name="B">10 6378137 20</CgPoint></CgPoints>
    <Survey><SurveyHeader name="external"/><GPSSetup id="s1" stationName="A" antennaHeight="0"/>
    <GPSSetup id="s2" stationName="B" antennaHeight="0"/>
    <GPSVector setupID_A="s1" setupID_B="s2" dX="0" dY="10" dZ="20"><TargetPoint pntRef="B"/></GPSVector></Survey></LandXML>''')
    with pytest.raises(ValueError, match='coordinate_frame'):
        import_landxml(path)
    with pytest.raises(ValueError, match='VCV'):
        import_landxml(path, coordinate_frame='ECEF')
    net = import_landxml(path, coordinate_frame='ECEF', default_sigma=.01)
    np.testing.assert_array_equal(net.baselines[0].delta, [0, 10, 20])
    tree = ET.parse(path)
    tree.find('.//{'+NS+'}GPSSetup').set('antennaHeight', '1')
    tree.write(path)
    with pytest.raises(ValueError, match='天线高'):
        import_landxml(path, coordinate_frame='ECEF', default_sigma=.01)


def test_reject_version_units_and_bad_refs(tmp_path):
    net, _ = correlated_network()
    path = export_landxml(net, tmp_path/'s.xml')
    tree = ET.parse(path)
    tree.getroot().set('version', '1.1')
    tree.write(path)
    with pytest.raises(ValueError, match='1.2'):
        import_landxml(path)
