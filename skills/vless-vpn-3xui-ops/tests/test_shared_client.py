from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE.parent / "scripts" / "_vendor" / "xui_api.py"
SHARED = HERE.parents[1] / "vless-vpn-3xui-skill" / "scripts" / "xui_api.py"


def test_vendored_client_is_identical_to_setup_skill():
    if not SHARED.exists():
        return  # skill copied on its own; nothing to compare
    assert VENDOR.read_bytes() == SHARED.read_bytes(), (
        "scripts/_vendor/xui_api.py drifted from the setup skill; "
        "cp ../vless-vpn-3xui-skill/scripts/xui_api.py scripts/_vendor/"
    )


def test_cloud_preflight_identical_in_both_skills():
    a = HERE.parent / "scripts" / "cloud-preflight.sh"
    b = HERE.parents[1] / "vless-vpn-3xui-skill" / "scripts" / "cloud-preflight.sh"
    if b.exists():
        assert a.read_bytes() == b.read_bytes(), "cp scripts/cloud-preflight.sh ../vless-vpn-3xui-skill/scripts/"
