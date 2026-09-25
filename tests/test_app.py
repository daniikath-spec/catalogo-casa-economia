import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import processor


def sample_png():
    im = Image.new('RGBA', (640, 900), '#ffffff')
    for x in range(100, 540):
        for y in range(100, 810):
            im.putpixel((x, y), (100+(x%20), 20+(y%20), 150, 255))
    b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()


def test_jpg_contract():
    im = Image.open(io.BytesIO(sample_png()))
    out = processor.make_jpg(im)
    assert 60*1024 <= len(out) <= 120*1024, len(out)
    loaded = Image.open(io.BytesIO(out))
    assert loaded.size == (800, 800) and loaded.format == 'JPEG'
    assert loaded.getpixel((0,0)) == (255,255,255)
    print(f'PASS jpg: {loaded.size}, {len(out)} bytes, white corner')


def test_zip():
    with tempfile.TemporaryDirectory() as t:
        p=Path(t);(p/'results').mkdir();(p/'uploads').mkdir()
        (p/'results'/'7861048601566.jpg').write_bytes(processor.make_jpg(Image.open(io.BytesIO(sample_png()))))
        (p/'uploads'/'0001_producto.jpg').write_bytes(b'photo')
        (p/'uploads'/'0001_codigo.jpg').write_bytes(b'barcode')
        rows=[dict(par=1,estado='OK',archivo_jpg='7861048601566.jpg'),dict(par=2,estado='PENDIENTE',detalle='ilegible')]
        processor.create_zip(p,rows,p/'done.zip')
        with zipfile.ZipFile(p/'done.zip') as z:
            assert 'PRODUCTOS_PROCESADOS/7861048601566.jpg' in z.namelist()
            assert 'reporte.csv' in z.namelist()
            assert 'PENDIENTES_REVISION/0001_codigo.jpg' in z.namelist()
        print('PASS zip: jpg + report + pending photos')


def test_real_barcodes():
    src=Path('/mnt/data')
    expected={'IMG_0203.jpeg':'7861048601566','IMG_0207.jpeg':'7861048602549'}
    for filename,barcode in expected.items():
        if (src/filename).is_file():
            assert barcode in processor.get_barcodes(src/filename)
    if (src/'IMG_0205.jpeg').is_file():
        found=processor.get_barcodes(src/'IMG_0205.jpeg')
        assert len(found)>=2,found
        print('PASS barcode: 2 detected, routed to manual review:',found)
    print('PASS real barcode photos: 0203 and 0207')


def test_http_upload():
    with tempfile.TemporaryDirectory() as t:
        os.environ['DATA_DIR']=t
        os.environ['APP_PASSWORD']='test-password'
        import importlib
        import app
        importlib.reload(app)
        client=TestClient(app.app)
        auth={'X-App-Key':'test-password'}
        assert client.post('/api/jobs').status_code==401
        assert client.get('/').status_code==200
        job=client.post('/api/jobs',headers=auth).json()['job']
        photo=sample_png()
        r=client.post(f'/api/jobs/{job}/upload',headers=auth,data={'index':'0'},files={
            'product':('front.png', photo,'image/png'),
            'barcode':('back.png',photo,'image/png')})
        assert r.status_code==200,r.text
        assert r.json()['received']==1
        s=client.get(f'/api/jobs/{job}',headers=auth).json()
        assert s['received']==1
        print('PASS HTTP: authentication, page, pair upload and status')


def test_end_to_end_from_uploaded_photos():
    sample_barcode=Path('/mnt/data/IMG_0203.jpeg')
    if not sample_barcode.exists():
        return
    with tempfile.TemporaryDirectory() as t:
        os.environ['DATA_DIR']=t
        os.environ['APP_PASSWORD']='test-password'
        import importlib
        import app
        importlib.reload(app)
        client=TestClient(app.app)
        h={'X-App-Key':'test-password'}
        job=client.post('/api/jobs',headers=h).json()['job']
        im=sample_png()
        with sample_barcode.open('rb') as f:
            response=client.post(f'/api/jobs/{job}/upload',headers=h,data={'index':'0'},files={'product':('f.png',im,'image/png'),'barcode':('b.jpeg',f,'image/jpeg')})
        assert response.status_code==200,response.text
        with patch.object(app,'remove_background',return_value=Image.open(io.BytesIO(im))):
            app.worker(Path(t)/job,1)
        status=client.get(f'/api/jobs/{job}',headers=h).json()
        assert status['state']=='done' and status['ok']==1,status
        download=client.get(f'/api/jobs/{job}/download',headers=h)
        assert download.status_code==200
        with zipfile.ZipFile(io.BytesIO(download.content)) as z:
            jpg=z.read('PRODUCTOS_PROCESADOS/7861048601566.jpg')
            assert 60*1024 <= len(jpg) <=120*1024
            assert Image.open(io.BytesIO(jpg)).size ==(800,800)
        print('PASS end-to-end: photo + real barcode -> coded JPG in downloadable ZIP')
