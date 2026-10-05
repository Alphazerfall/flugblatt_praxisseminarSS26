import base64

from fix_image_collisions import SRC, fix_doc, unique_batch_images


def picture(name, data):
    return {"block_type": "Picture", "html": f'<img src="{name}"/>',
            "images": {name: base64.b64encode(data).decode()}}


def test_shared_names_get_their_own_files():
    shared, alone = "a" * 32 + "_img.jpg", "b" * 32 + "_img.jpg"
    blocks = [picture(shared, b"portrait"), picture(shared, b"peace"), picture(alone, b"logo")]
    doc = {"children": [{"children": blocks[:1]}, {"children": blocks[1:]}]}

    assert sorted(fix_doc(doc).values()) == [b"peace", b"portrait"]
    names = [SRC.search(b["html"])[1] for b in blocks]
    assert len(set(names)) == 3 and names[2] == alone
    assert all(list(b["images"]) == [n] for b, n in zip(blocks, names))
    assert fix_doc(doc) == {}  # a second run changes nothing


def test_batches_get_distinct_names():
    name = "a" * 32 + "_img.jpg"
    first, second = (unique_batch_images({"json": {"html": f'src="{name}"'}, "images": {name: d}}, "json", i)
                     for i, d in enumerate("xy"))
    assert list(first["images"]) != list(second["images"])
    assert list(first["images"])[0] in first["json"]["html"]
