"""生成小型离线 DEM 瓦片及非线性配准报告。"""
from pathlib import Path
import io
import numpy as np
from PIL import Image
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from ctrlnet.terrain import DEM
from ctrlnet.webmap.render import render_hillshade_png
from ctrlnet.tiles import image_to_mbtiles, MBTiles
from ctrlnet.georef import fit

ROOT = Path(__file__).resolve().parents[1]


def main():
    sample=ROOT/'data/sample'
    out=ROOT/'outputs'; out.mkdir(exist_ok=True)
    dem=DEM.from_geotiff(sample/'dem_sample.tif')
    rgba=np.array(Image.open(io.BytesIO(render_hillshade_png(dem,scale=1))).convert('RGBA'))
    with rasterio.open(sample/'dem_sample.tif') as src:
        transform,width,height=calculate_default_transform(src.crs,'EPSG:3857',src.width,src.height,*src.bounds)
        target=np.zeros((height,width,4),dtype=np.uint8)
        for i in range(4):
            reproject(rgba[:,:,i],target[:,:,i],src_transform=src.transform,src_crs=src.crs,dst_transform=transform,dst_crs='EPSG:3857',resampling=Resampling.bilinear)
    bounds=rasterio.transform.array_bounds(height,width,transform)
    path=sample/'demo_tiles.mbtiles'
    if path.exists(): path.unlink()
    count=image_to_mbtiles(Image.fromarray(target),bounds,[11,12,13],path)
    assert path.stat().st_size <= 2*1024*1024
    with MBTiles(path,readonly=True) as db:
        metadata=db.metadata
        z,x,row=db.connection.execute('SELECT zoom_level,tile_column,tile_row FROM tiles LIMIT 1').fetchone()
        url=f'/tiles/demo_tiles/{z}/{x}/{2**z-1-row}.png'
    (out/'tiles_results.md').write_text(f'# 离线 MBTiles 演示\n\n来源：dem_sample.tif 晕渲，重投影 EPSG:3857。\n\n- zoom：11–13\n- 瓦片：{count} 张，256×256 PNG\n- 文件：data/sample/demo_tiles.mbtiles（{path.stat().st_size} bytes）\n- 数据库存储 TMS；公共读取与目录导出使用 XYZ。\n- 本地只读路由示例：`{url}`\n- 网页图层下拉选择 demo_tiles；预览重投影回工程坐标。\n- bounds（经纬度）：{metadata["bounds"]}\n',encoding='utf-8')
    p=np.array([(x,y) for x in range(4) for y in range(4)],float)
    checks=np.array([[.3,.6],[1.4,2.2]])
    lines=['# 多项式 / TPS 配准演示','', '| 模型 | 控制点 RMSE | 独立检查点 RMSE | 逆解最大误差 |','|---|---:|---:|---:|']
    for model,degree in [('polynomial',2),('polynomial',3),('tps',2)]:
        def truth(a):
            x,y=a.T
            return np.column_stack((100+2*x+.02*y**degree,200+3*y+.03*x*x))
        r=fit(np.column_stack((p,truth(p))),np.column_stack((checks,truth(checks))),model=model,degree=degree)
        inverse_error=np.max(np.abs(r.inverse(r.transform(checks))-checks))
        lines.append(f'| {model} {degree if model == "polynomial" else ""} | {r.rmse:.3e} | {r.check_rmse:.3e} | {inverse_error:.3e} |')
    lines += ['', '误差单位与目标平面坐标一致；检查点不参与拟合。TPS 精确插值控制点，但独立位置不必精确恢复多项式。逆解仅保证收敛位置的局部解。']
    (out/'georef_results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(f'{count} tiles, {path.stat().st_size} bytes; outputs/georef_results.md; outputs/tiles_results.md')


if __name__ == '__main__':
    main()
