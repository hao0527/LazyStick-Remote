"""Build the helper and whitelist-only source/download archives on Windows."""
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "huawei-auth"
BUILD = ROOT / ".auth-build"
DOWNLOADS = PAGE / "downloads"


def main():
    if sys.platform != "win32" or platform.architecture()[0] != "64bit":
        raise SystemExit("Build with 64-bit Python on Windows.")
    BUILD.mkdir(exist_ok=True)
    DOWNLOADS.mkdir(exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
                    "--name", "LazyStick-Huawei-Auth", "--distpath", str(BUILD / "dist"),
                    "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
                    "--add-data", str(PAGE / "index.html") + ";ui",
                    "--add-data", str(PAGE / "app.js") + ";ui",
                    "--add-data", str(PAGE / "style.css") + ";ui",
                    str(PAGE / "helper/main.py")], check=True, cwd=ROOT)

    source = DOWNLOADS / "LazyStick-Huawei-Auth-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(PAGE.rglob("*")):
            relative = item.relative_to(PAGE)
            if not item.is_file() or any(part in {"downloads", "__pycache__"} for part in relative.parts):
                continue
            if item.suffix not in {".py", ".js", ".html", ".css", ".md", ".txt"} and item.name != "LICENSE":
                continue
            archive.write(item, "huawei-auth/" + relative.as_posix())
        archive.write(__file__, "scripts/build-huawei-auth.py")

    binary = DOWNLOADS / "LazyStick-Huawei-Auth-windows-x64.zip"
    with zipfile.ZipFile(binary, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(BUILD / "dist/LazyStick-Huawei-Auth.exe", "LazyStick-Huawei-Auth.exe")
        archive.write(PAGE / "README.md", "README.md")
        archive.write(PAGE / "helper/vendor/huawei_smarthome/LICENSE", "LICENSE")
        archive.write(PAGE / "helper/vendor/UPSTREAM.md", "PROTOCOL-SOURCE.md")
        archive.write(source, "source.zip")
        archive.writestr("使用本地页面.cmd", '@echo off\r\n"%~dp0LazyStick-Huawei-Auth.exe" --local\r\n')
        archive.writestr("THIRD-PARTY.txt", "Python https://www.python.org/psf/license/\n"
                          "PyInstaller https://pyinstaller.org/en/stable/license.html\n"
                          "Bundled dependency licenses are in licenses/.\n")
        archive.write(Path(sys.base_prefix) / "LICENSE.txt", "licenses/Python-LICENSE.txt")
        for distribution in metadata.distributions():
            name = distribution.metadata["Name"]
            for item in distribution.files or ():
                if any(word in item.name.upper() for word in ["LICENSE", "COPYING", "NOTICE"]):
                    path = distribution.locate_file(item)
                    if path.is_file():
                        safe_path = "/".join(p for p in str(item).replace("\\", "/").split("/") if p not in {"..", ".", ""})
                        archive.write(path, "licenses/" + name + "/" + safe_path)
    artifacts = [{"file": p.name, "size": p.stat().st_size,
                  "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (binary, source)]
    (DOWNLOADS / "manifest.json").write_text(json.dumps({"version": "1.0.0", "artifacts": artifacts}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifacts, indent=2))


if __name__ == "__main__":
    main()
