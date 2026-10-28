from importlib.resources import files


def test_prompt_is_packaged():
    assert (files("fieldnote") / "system_prompt.txt").is_file()


def test_web_page_is_packaged():
    assert (files("fieldnote") / "index.html").is_file()
