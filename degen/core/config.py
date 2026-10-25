import yaml, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
def load(path: str | None = None) -> dict:
    return yaml.safe_load(open(path or ROOT / "config.yaml"))
