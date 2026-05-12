import json
import os


def test_nodes_file_path_override(tmp_path, monkeypatch):
    # Arrange settings
    nodes_path = tmp_path / "custom_nodes.json"
    monkeypatch.setenv("PYTHONPATH", os.getenv("PYTHONPATH", ""))

    # Prepare a minimal nodes file with extended fields
    raw = {
        "hk1": {
            "hotkey": "hk1",
            "coldkey": "ck1",
            "node_id": 1,
            "incentive": 0.0,
            "netuid": 1,
            "alpha_stake": 0.0,
            "tao_stake": 0.0,
            "stake": 0.0,
            "trust": 0.0,
            "vtrust": 0.0,
            "last_updated": 0.0,
            "ip": "0.0.0.0",
            "ip_type": 4,
            "port": 0,
            "protocol": 4,
            "version": "1.2.3",
            "is_validator": True,
        }
    }
    nodes_path.write_text(json.dumps(raw))

    # Patch settings to point to our nodes file
    from subnet_validator import settings as app_settings

    app_settings.Settings.model_rebuild()
    s = app_settings.Settings(nodes_file=str(nodes_path))

    # Import and instantiate ExtendedMetagraph with load_old_nodes=True and no substrate
    from subnet_validator.fiber_ext.metagraph import ExtendedMetagraph

    mg = ExtendedMetagraph(substrate=None, netuid="1", load_old_nodes=True)
    # It should load from file without errors
    assert "hk1" in mg.nodes
    node = mg.nodes["hk1"]
    assert getattr(node, "version") == "1.2.3"
    assert getattr(node, "is_validator") is True
