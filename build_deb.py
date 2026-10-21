#!/usr/bin/python3
"""Build an architecture-independent Debian package without root."""

import ast
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def package_version():
    module = ast.parse((ROOT / "zprint_app/__init__.py").read_text())
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in statement.targets
        ):
            return ast.literal_eval(statement.value)
    raise RuntimeError("Missing __version__")


def build():
    version = package_version()
    deb_version = version + "-1"
    subprocess.run(["dpkg", "--validate-version", deb_version], check=True)
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    artifact = output / f"zprint_{deb_version}_all.deb"
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    with tempfile.TemporaryDirectory(prefix="zprint-deb-") as folder:
        stage = Path(folder)

        def copy(source, destination, executable=False):
            target = stage / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
            target.chmod(0o755 if executable else 0o644)

        for source in sorted((ROOT / "zprint_app").iterdir()):
            if source.suffix in (".py", ".css"):
                copy(source, Path("usr/lib/zprint/zprint_app") / source.name)
        copy("zprint", "usr/lib/zprint/zprint", True)
        copy("packaging/zprint", "usr/bin/zprint", True)
        copy("packaging/io.github.zprint.Zprint.desktop", "usr/share/applications/io.github.zprint.Zprint.desktop")
        copy("assets/zprint.svg", "usr/share/icons/hicolor/scalable/apps/zprint.svg")
        copy("README.md", "usr/share/doc/zprint/README.md")
        copy(f"releases/v{version}.md", "usr/share/doc/zprint/RELEASE_NOTES.md")
        changelog = stage / "usr/share/doc/zprint/changelog.gz"
        with changelog.open("wb") as stream:
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=epoch) as zipped:
                zipped.write((ROOT / "CHANGELOG.md").read_bytes())
        size = sum(path.stat().st_size for path in (stage / "usr").rglob("*") if path.is_file())
        control = stage / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            f"Package: zprint\nVersion: {deb_version}\nArchitecture: all\n"
            "Section: graphics\nPriority: optional\n"
            "Maintainer: zhou411X <216644640+zhou411X@users.noreply.github.com>\n"
            f"Installed-Size: {(size + 1023) // 1024}\n"
            "Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, python3-cairo, "
            "python3-pil (>= 9.1), gir1.2-gtk-3.0, librsvg2-common, "
            "gsettings-desktop-schemas, gnome-settings-daemon-common, xdg-desktop-portal, "
            "dconf-gsettings-backend | gsettings-backend\n"
            "Recommends: xdg-desktop-portal-gnome, desktop-file-utils, libgtk-3-bin\n"
            "Homepage: https://github.com/zhou411X/zprint\n"
            "Description: Native screenshot annotation editor for GNOME and Wayland\n"
            " Capture through the system screenshot portal and annotate images with arrows,\n"
            " freehand strokes, text, shapes, pixelation and numbered markers. Supports\n"
            " clipboard images, PNG/JPEG export and configurable GNOME global shortcuts.\n"
        )
        for script in ("postinst", "postrm"):
            copy("packaging/" + script, "DEBIAN/" + script, True)
        paths = sorted(path for path in (stage / "usr").rglob("*") if path.is_file())
        (control / "md5sums").write_text("".join(
            f"{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(stage)}\n" for path in paths
        ))
        for path in stage.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            else:
                path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
            os.utime(path, (epoch, epoch))
        stage.chmod(0o755)
        os.utime(stage, (epoch, epoch))
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(stage), str(artifact)],
                       check=True, env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch)})
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{checksum}  {artifact.name}\n")
    print(f"Built {artifact}\nSHA256 {checksum}")


if __name__ == "__main__":
    build()
