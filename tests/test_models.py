"""Test rio_tiler.models."""

from io import BytesIO

import numpy
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.io import MemoryFile

from rio_tiler.errors import InvalidDatatypeWarning, InvalidPointDataError
from rio_tiler.models import ImageData, PointData


def test_imageData_AutoRescaling():
    """Test ImageData auto rescaling."""
    with pytest.warns(InvalidDatatypeWarning) as w:
        ImageData(numpy.zeros((1, 256, 256), dtype="float32")).render(img_format="PNG")
        assert len(w.list) == 1

    with pytest.warns(None) as w:
        ImageData(numpy.zeros((1, 256, 256), dtype="uint8")).render(img_format="PNG")
        assert len(w.list) == 0

    with pytest.warns(InvalidDatatypeWarning) as w:
        ImageData(numpy.zeros((1, 256, 256), dtype="int8")).render(img_format="PNG")

    with pytest.warns(None) as w:
        ImageData(numpy.zeros((1, 256, 256), dtype="uint16")).render(img_format="GTiff")
        assert len(w.list) == 0

    with pytest.warns(InvalidDatatypeWarning) as w:
        ImageData(numpy.zeros((1, 256, 256), dtype="uint16")).render(img_format="jpeg")

    with pytest.warns(InvalidDatatypeWarning) as w:
        ImageData(numpy.zeros((3, 256, 256), dtype="uint16")).render(img_format="WEBP")

    with pytest.warns(InvalidDatatypeWarning) as w:
        ImageData(numpy.zeros((3, 256, 256), dtype="int8")).render(
            img_format="JP2OpenJPEG"
        )

    # Make sure that we do not rescale uint16 data when there is a colormap
    with pytest.warns(None) as w:
        cm = {1: (0, 0, 0, 255), 1000: (255, 255, 255, 255)}
        ImageData(numpy.zeros((1, 256, 256), dtype="uint16")).render(
            img_format="JPEG", colormap=cm
        )
        assert len(w.list) == 0


@pytest.mark.parametrize(
    "dtype",
    ["uint8", "int8", "uint16", "int16", "uint32", "int32", "float32", "float64"],
)
def test_imageData_AutoRescalingAllTypes(dtype):
    """Test ImageData auto rescaling."""
    with pytest.warns(None):
        ImageData(numpy.zeros((1, 256, 256), dtype=dtype)).render(img_format="PNG")
        ImageData(numpy.zeros((1, 256, 256), dtype=dtype)).render(img_format="JPEG")
        ImageData(numpy.zeros((3, 256, 256), dtype=dtype)).render(img_format="WEBP")
        ImageData(numpy.zeros((3, 256, 256), dtype=dtype)).render(
            img_format="JP2OPENJPEG"
        )


def test_16bit_PNG():
    """Uint16 Mask value should be between 0 and 65535 for PNG."""
    mask = numpy.zeros((1, 256, 256), dtype="bool")
    mask[0:10, 0:10] = True

    with pytest.warns(None):
        arr = numpy.ma.MaskedArray(numpy.zeros((1, 256, 256), dtype="uint16"))
        arr.mask = mask.copy()
        img = ImageData(arr).render(img_format="PNG")

        with rasterio.open(BytesIO(img)) as src:
            assert src.count == 2
            assert src.meta["dtype"] == "uint16"
            arr = src.read(2)
            assert arr.min() == 0
            assert arr.max() == 65535
            assert (arr[0:10, 0:10] == 0).all()
            assert (arr[11:, 11:] == 65535).all()

    with pytest.warns(None):
        arr = numpy.ma.MaskedArray(numpy.zeros((3, 256, 256), dtype="uint16"))
        arr.mask = mask.copy()
        img = ImageData(arr).render(img_format="PNG")

        with rasterio.open(BytesIO(img)) as src:
            assert src.count == 4
            assert src.meta["dtype"] == "uint16"
            arr = src.read(4)
            assert arr.min() == 0
            assert arr.max() == 65535
            assert (arr[0:10, 0:10] == 0).all()
            assert (arr[11:, 11:] == 65535).all()


def test_merge_with_diffsize():
    """Make sure we raise a warning"""
    mask = numpy.zeros((256, 256), dtype="uint16") + 255
    mask[0:10, 0:10] = 0
    mask[10:11, 10:11] = 100

    with pytest.warns(UserWarning):
        img1 = ImageData(numpy.zeros((1, 256, 256)))
        img2 = ImageData(numpy.zeros((1, 128, 128)))
        img = ImageData.create_from_list([img1, img2])

    assert img.count == 2
    assert img.width == 256
    assert img.height == 256

    with pytest.warns(None) as w:
        img1 = ImageData(numpy.zeros((1, 256, 256)))
        img2 = ImageData(numpy.zeros((1, 256, 256)))
        img = ImageData.create_from_list([img1, img2])
    assert len(w) == 0


def test_apply_expression():
    """Apply expression"""
    img = ImageData(numpy.zeros((2, 256, 256)))
    img2 = img.apply_expression("b1+b2")
    assert img.count == 2
    assert img.width == 256
    assert img.height == 256
    assert img.band_names == ["b1", "b2"]
    assert img2.count == 1
    assert img2.width == 256
    assert img2.height == 256
    assert img2.band_names == ["b1+b2"]


def test_dataset_statistics():
    """Make statistics are preserved on expression"""
    data = numpy.zeros((2, 256, 256), dtype="uint8")
    data[0, 0:10, 0:10] = 0
    data[0, 10:11, 10:11] = 100
    data[1, 0:10, 0:10] = 100
    data[1, 10:11, 10:11] = 200
    img = ImageData(data, dataset_statistics=[(0, 100), (0, 200)])

    img2 = img.apply_expression("b1+b2")
    assert img2.dataset_statistics == [(0, 300)]

    img2 = img.apply_expression("b1+b2;b1*b2;b1/b1")
    assert img2.dataset_statistics == [(0, 300), (0, 20000), (0, 1)]
    assert img2.data[0].min() == 0
    assert img2.data[0].max() == 300
    assert img2.data[1].min() == 0
    assert img2.data[1].max() == 20000
    assert img2.data[2].min() == 0
    assert img2.data[2].max() == 1

    data = numpy.zeros((1, 256, 256), dtype="int16")
    data[0, 0:10, 0:10] = 0
    data[0, 10:11, 10:11] = 1

    img = ImageData(data, dataset_statistics=[(0, 1)]).render(img_format="PNG")
    with MemoryFile(img) as mem:
        with mem.open() as dst:
            arr = dst.read(indexes=1)
            assert arr.min() == 0
            assert arr.max() == 255

    img = ImageData(data).render(img_format="PNG")
    with MemoryFile(img) as mem:
        with mem.open() as dst:
            arr = dst.read(indexes=1)
            assert not arr.min() == 0
            assert not arr.max() == 255


def test_resize():
    """Resize ImageData and check original image"""
    data = numpy.zeros((3, 1024, 1024), dtype="uint8")
    img = ImageData(data)

    img_r = img.resize(256, 256)
    assert img_r.count == 3
    assert img_r.width == 256
    assert img_r.height == 256
    assert img.width == 1024
    assert img.height == 1024
    assert img_r.mask.shape == (256, 256)
    assert img.mask.shape == (1024, 1024)


def test_clip():
    """Resize ImageData and check original image"""
    data = numpy.zeros((3, 1024, 1024), dtype="uint8")
    img = ImageData(data, crs="epsg:4326", bounds=(-180, -90, 180, 90))

    img_c = img.clip((-100, -50, 100, 50))
    assert img_c.count == 3
    assert img_c.bounds == (-100, -50, 100, 50)

    assert img.width == 1024
    assert img.height == 1024
    assert img.mask.shape == (1024, 1024)


def test_point_data():
    """Test Point Data Model."""
    pt = PointData(numpy.zeros((3), dtype="uint16"))
    assert pt.count == 3
    assert pt.data.shape == (3,)
    assert pt.mask.shape == (1,)
    assert pt.mask.tolist() == [255]
    assert pt.band_names == ["b1", "b2", "b3"]

    with pytest.raises(ValueError):
        PointData(numpy.zeros((3, 3)))

    with pytest.raises(ValueError):
        PointData(numpy.zeros((3), dtype="uint16"), coordinates=(0,))

    for p in PointData(numpy.zeros((3), dtype="uint16")):
        assert p == 0

    pt = PointData(numpy.zeros((3), dtype="uint16"))
    arr = pt.as_masked()
    assert numpy.ma.is_mask(arr.mask)

    pt1 = PointData(numpy.array([1, 2]))
    pt2 = pt1.apply_expression("b1+b2")
    assert pt1.count == 2
    assert pt1.band_names == ["b1", "b2"]
    assert pt2.count == 1
    assert pt2.band_names == ["b1+b2"]

    pts = PointData.create_from_list([pt1, pt2])
    assert pts.data.tolist() == [1, 2, 3]
    assert pts.band_names == ["b1", "b2", "b1+b2"]
    assert pts.mask.tolist() == [255]

    pts = PointData.create_from_list(
        [
            PointData(numpy.ma.MaskedArray([1], [0])),
            PointData(numpy.ma.MaskedArray([1], [1])),
        ]
    )
    assert pts.array.mask.tolist() == [False, True]
    assert pts.mask.tolist() == [0]

    pts = PointData.create_from_list(
        [
            PointData(numpy.ma.MaskedArray([1], [0])),
            PointData(numpy.ma.MaskedArray([1], [0])),
        ]
    )
    assert pts.array.mask.tolist() == [False, False]
    assert pts.mask.tolist() == [255]

    pts = PointData.create_from_list(
        [
            PointData(numpy.ma.MaskedArray([1], [1])),
            PointData(numpy.ma.MaskedArray([1], [1])),
        ]
    )
    assert pts.array.mask.tolist() == [True, True]
    assert pts.mask.tolist() == [0]

    with pytest.raises(InvalidPointDataError):
        PointData.create_from_list([])

    with pytest.raises(InvalidPointDataError):
        PointData.create_from_list(
            [
                PointData(numpy.ma.MaskedArray([1]), coordinates=(0, 0)),
                PointData(numpy.ma.MaskedArray([1]), coordinates=(0, 1)),
            ]
        )

    with pytest.raises(InvalidPointDataError):
        PointData.create_from_list(
            [
                PointData(
                    numpy.ma.MaskedArray([1]),
                    coordinates=(0, 0),
                    crs=CRS.from_epsg(3857),
                ),
                PointData(
                    numpy.ma.MaskedArray([1]),
                    coordinates=(0, 0),
                    crs=CRS.from_epsg(4326),
                ),
            ]
        )


def test_image_apply_colormap():
    """Apply colormap to the data."""
    cm = {0: (0, 0, 0, 255), 1: (255, 255, 255, 255)}
    im = ImageData(numpy.zeros((1, 256, 256), dtype="uint8")).apply_colormap(cm)
    assert im.data.shape == (3, 256, 256)
    assert im.data[:, 0, 0].tolist() == [0, 0, 0]
    assert im.mask[0, 0] == 255
    assert im.mask.all()

    cm = {0: (0, 0, 0, 255), 1: (255, 255, 255, 255)}
    data = numpy.zeros((1, 256, 256), dtype="uint8") + 1
    data[0, 0, 0] = 0

    im = ImageData(data)
    assert im.array.data.shape == (1, 256, 256)
    assert im.array.mask.shape == (1, 256, 256)

    im = im.apply_colormap(cm)
    # data[0, 1, 1] is 1 so after colormap it should be 255,255,255 and mask should be 255
    assert im.data[:, 1, 1].tolist() == [255, 255, 255]
    assert im.array.data.shape == (3, 256, 256)
    assert im.array.mask.shape == (3, 256, 256)
    assert im.mask[1, 1] == 255

    # data[0, 0, 0] is 0 so after colormap it should be 0,0,0 and mask should be 255 (based on the colormap Alpha value)
    assert im.data[:, 0, 0].tolist() == [0, 0, 0]
    assert im.mask[0, 0] == 255

    cm = {0: (0, 0, 0, 255), 1: (255, 255, 255, 255)}
    arr = numpy.zeros((1, 256, 256), dtype="uint8") + 1
    arr[0, 0, 0] = 0

    mask = numpy.zeros((1, 256, 256), dtype="bool")
    mask[0, 0, 0] = True

    im = ImageData(numpy.ma.MaskedArray(arr, mask=mask)).apply_colormap(cm)
    # data[0, 0, 0] is 0 so after colormap it should be 0,0,0 and mask should be 0 (because it was masked by the original mask)
    assert im.data[:, 0, 0].tolist() == [0, 0, 0]
    assert im.array.mask[:, 1, 1].tolist() == [False, False, False]
    assert im.mask[1, 1] == 255

    assert im.array.mask[:, 0, 0].tolist() == [True, True, True]
    assert im.mask[0, 0] == 0


def test_image_from_array():
    """Create ImageData from arrays."""
    arr = numpy.zeros((1, 256, 256), dtype="uint8")
    im = ImageData.from_array(arr)
    assert im.data.shape == (1, 256, 256)
    assert im.mask.all()

    arr = numpy.ma.MaskedArray(numpy.zeros((1, 256, 256), dtype="uint8"))
    im = ImageData.from_array(arr)
    assert im.data.shape == (1, 256, 256)
    assert im.mask.all()

    arr = numpy.ma.MaskedArray(
        numpy.zeros((1, 256, 256), dtype="uint8"),
        mask=numpy.zeros((256, 256), dtype="uint8"),
    )
    im = ImageData.from_array(arr)
    assert im.data.shape == (1, 256, 256)
    assert im.mask.all()

    mask = numpy.zeros((256, 256), dtype="uint8")  # 0 no masked
    mask[0:10, 0:10] = 1  # masked
    arr = numpy.ma.MaskedArray(
        numpy.zeros((1, 256, 256), dtype="uint8"),
        mask,
    )
    im = ImageData.from_array(arr)
    assert im.data.shape == (1, 256, 256)
    assert not im.mask.all()
    assert im.mask[0, 0] == 0
    assert im.mask[11, 11] == 255


def test_image_from_bytes():
    """Create ImageData from bytes."""
    im = ImageData(numpy.zeros((1, 256, 256), dtype="uint8"))
    assert im.data.shape == (1, 256, 256)

    im_r = ImageData.from_bytes(im.render(img_format="PNG", add_mask=True))
    assert im_r.data.shape == (1, 256, 256)
    assert im.mask.all()

    data = numpy.zeros((1, 256, 256), dtype="uint8")
    data[0:100, 0:100] = 1
    mask = numpy.zeros((1, 256, 256), dtype="bool")
    mask[0:10, 0:10] = True
    img = ImageData(numpy.ma.MaskedArray(data, mask=mask))

    im = ImageData.from_bytes(img.render(img_format="PNG", add_mask=True))
    assert im.data.shape == (1, 256, 256)
    assert not im.mask.all()

    im = ImageData.from_bytes(img.render(img_format="PNG", add_mask=False))
    assert im.data.shape == (1, 256, 256)
    assert im.mask.all()

    im = ImageData.from_bytes(img.render(img_format="JPEG", add_mask=False))
    assert im.data.shape == (1, 256, 256)
    assert im.mask.all()


def test_2d_image():
    """Create Image Data from 2d array."""
    data = numpy.zeros((256, 256))
    im = ImageData(data)
    assert im.count == 1
    assert im.width == 256
    assert im.height == 256
    assert im.mask.all()
