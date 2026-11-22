import pytest

@pytest.fixture(autouse=True)
def isolated_output_directory(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPER_MODELAR_DATA_DIR', str(tmp_path/'data'))
