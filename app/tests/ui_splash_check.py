"""启动界面截图自查（无头 Edge，不开任何 GUI 窗口、不连 Lightroom，不属于 pytest）。
用法：python app/tests/ui_splash_check.py <截图输出目录>
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import settings as st  # noqa: E402
import splash  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, text in (("check", splash.TEXT_CHECK), ("services", splash.TEXT_SERVICES), ("launch_lr", splash.TEXT_LAUNCH_LR),
                       ("connect_lr", splash.TEXT_CONNECT_LR)):
        with tempfile.TemporaryDirectory() as d:
            page = Path(d) / "splash.html"
            page.write_text(splash.splash_html(st.APP_VERSION, text), encoding="utf-8")
            target = out / f"splash_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--window-size={splash.WIDTH},{splash.HEIGHT}", "--virtual-time-budget=2000",
                            f"--screenshot={target}", page.as_uri()], check=True, timeout=60, capture_output=True)
            print("截图", target)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
