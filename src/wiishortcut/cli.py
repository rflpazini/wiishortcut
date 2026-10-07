"""The ``wiishortcut`` command. Human output is plain text. ``--json`` is for scripts."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import typer
from rich.console import Console

from wiishortcut import __version__
from wiishortcut.config import key_status, load_config
from wiishortcut.errors import WiiShortcutError
from wiishortcut.forwarder.assets import asset_for, install_asset, load_manifest, verify_installed
from wiishortcut.pipeline import (
    CreateResult,
    PlannedGame,
    create_shortcut,
    format_batch,
    format_create,
    format_dry_run,
    format_inspect,
    inspect_game,
    run_batch,
    validate_file,
)
from wiishortcut.wad.validator import describe_wad, format_report

console = Console(highlight=False, markup=False, soft_wrap=True, emoji=False)
err_console = Console(highlight=False, markup=False, soft_wrap=True, emoji=False, stderr=True)
app = typer.Typer(no_args_is_help=True, add_completion=False)
assets_app = typer.Typer(no_args_is_help=True, add_completion=False)
wad_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(assets_app, name="assets")
app.add_typer(wad_app, name="wad")


def _print_version(value: bool) -> None:
    if not value:
        return
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as package_version

    try:
        library = package_version("libWiiPy")
    except PackageNotFoundError:
        library = "unknown"
    console.print(f"wiishortcut {__version__}\nlibWiiPy {library}")
    raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    debug: bool = typer.Option(False, "--debug", help="Show parser decisions and tracebacks."),
    verbose: int = typer.Option(0, "-v", "--verbose", count=True, help="Repeat for more detail."),
    version: bool = typer.Option(False, "--version", callback=_print_version, is_eager=True),
) -> None:
    """Build Wii USB Loader GX shortcut channels."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    ctx.obj["verbose"] = 2 if debug else verbose


def _debug_enabled(ctx: typer.Context) -> bool:
    obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    return bool(obj.get("debug"))


def _verbose(ctx: typer.Context) -> bool:
    obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    return bool(obj.get("verbose"))


def _log(ctx: typer.Context, message: str) -> None:
    if _verbose(ctx):
        err_console.print(f"debug: {message}")


def _fail(ctx: typer.Context, json_output: bool, exc: WiiShortcutError) -> None:
    if json_output:
        payload = {"status": "error", "exit_code": exc.exit_code, "message": str(exc)}
        console.print(json.dumps(payload))
    else:
        err_console.print(str(exc))
        if _debug_enabled(ctx):
            traceback.print_exception(exc, file=sys.stderr)
    raise typer.Exit(code=exc.exit_code)


def _guard(ctx: typer.Context, json_output: bool, action):
    try:
        return action()
    except typer.Exit:
        raise
    except WiiShortcutError as exc:
        _fail(ctx, json_output, exc)
    except Exception as exc:
        if _debug_enabled(ctx):
            traceback.print_exc(file=sys.stderr)
        _fail(ctx, json_output, WiiShortcutError(f"Unexpected failure: {exc}"))


@app.command()
def inspect(
    ctx: typer.Context,
    image: Path = typer.Argument(..., help="A .iso or .wbfs file."),
    game_id: str | None = typer.Option(None, "--game-id", help="Override the game ID."),
    name: str | None = typer.Option(None, "--name", help="Override the title."),
    source: str | None = typer.Option(None, "--source", help="usb or sd. Defaults to usb."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read the game ID, title, and region from a disc image."""

    def action() -> None:
        game = inspect_game(image, game_id=game_id, name=name)
        chosen = (source or load_config().source).strip().lower()
        if json_output:
            payload = {
                "status": "success",
                "format": game.format,
                "game_id": game.game_id,
                "title": game.title,
                "region": game.region,
                "loader": "usbloadergx",
                "source": chosen,
                "disc_number": game.disc_number,
                "disc_version": game.disc_version,
                "id_source": game.id_source,
            }
            console.print(json.dumps(payload))
            return
        console.print(format_inspect(game, source=chosen, verbose=_verbose(ctx)))

    _guard(ctx, json_output, action)


@app.command()
def create(
    ctx: typer.Context,
    image: Path = typer.Argument(..., help="A .iso or .wbfs file."),
    game_id: str | None = typer.Option(None, "--game-id"),
    name: str | None = typer.Option(None, "--name"),
    channel_id: str | None = typer.Option(None, "--channel-id"),
    output: Path | None = typer.Option(None, "--output"),
    loader: str | None = typer.Option(None, "--loader"),
    source: str | None = typer.Option(None, "--source"),
    ios: int | None = typer.Option(None, "--ios"),
    advanced: bool = typer.Option(False, "--advanced", help="Allow an IOS other than 58."),
    base_wad: Path | None = typer.Option(None, "--base-wad"),
    banner: Path | None = typer.Option(None, "--banner", help="A trusted opening.bnr to retitle."),
    forwarder: Path | None = typer.Option(None, "--forwarder"),
    manifest: bool = typer.Option(False, "--manifest", help="Write a .wad.json provenance file."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Build one USB Loader GX shortcut WAD."""

    def action() -> None:
        result = create_shortcut(
            image,
            game_id=game_id,
            name=name,
            channel_id=channel_id,
            output=output,
            loader=loader,
            source=source,
            ios=ios,
            advanced=advanced,
            base_wad=base_wad,
            banner=banner,
            forwarder=forwarder,
            write_manifest=manifest,
            log=lambda message: _log(ctx, message),
        )
        if json_output:
            console.print(json.dumps(_create_payload(result)))
            return
        console.print("Inspecting game...\n")
        console.print(format_create(result))

    _guard(ctx, json_output, action)


@app.command()
def validate(
    ctx: typer.Context,
    wad: Path = typer.Argument(..., help="A .wad file to check."),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Check a WAD's structure, hashes, banner, and forwarder."""

    def action() -> None:
        report = validate_file(wad, strict=strict)
        if json_output:
            payload = {
                "status": "valid" if report.ok else "invalid",
                "ok": report.ok,
                "game_id": report.game_id,
                "channel_id": report.channel_id,
                "ios": report.ios,
                "source": report.source,
                "checks": [
                    {"label": check.label, "state": check.state, "note": check.note}
                    for check in report.checks
                ],
            }
            console.print(json.dumps(payload))
        else:
            console.print(format_report(report))
        if not report.ok:
            raise typer.Exit(code=4)

    _guard(ctx, json_output, action)


@app.command()
def batch(
    ctx: typer.Context,
    library: Path = typer.Argument(..., help="A folder of .iso and .wbfs files."),
    output: Path = typer.Option(Path("wad"), "--output", help="Directory for the WAD files."),
    loader: str | None = typer.Option(None, "--loader"),
    source: str | None = typer.Option(None, "--source"),
    ios: int | None = typer.Option(None, "--ios"),
    advanced: bool = typer.Option(False, "--advanced"),
    base_wad: Path | None = typer.Option(None, "--base-wad"),
    banner: Path | None = typer.Option(None, "--banner"),
    forwarder: Path | None = typer.Option(None, "--forwarder"),
    manifest: bool = typer.Option(False, "--manifest"),
    dry_run: bool = typer.Option(False, "--dry-run", help="List the games and write nothing."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Build a WAD for every game in a folder."""

    def action() -> None:
        results = run_batch(
            library,
            output,
            loader=loader,
            source=source,
            ios=ios,
            advanced=advanced,
            base_wad=base_wad,
            banner=banner,
            forwarder=forwarder,
            write_manifest=manifest,
            dry_run=dry_run,
            log=lambda message: _log(ctx, message),
        )
        if dry_run:
            planned = [item for item in results if isinstance(item, PlannedGame)]
            if json_output:
                console.print(
                    json.dumps(
                        {
                            "status": "dry-run",
                            "count": len(planned),
                            "games": [
                                {
                                    "game_id": item.game.game_id,
                                    "title": item.game.title,
                                    "channel_id": item.channel_id,
                                    "output": str(item.output),
                                }
                                for item in planned
                            ],
                        }
                    )
                )
                return
            console.print(format_dry_run(planned))
            return
        built = [item for item in results if isinstance(item, CreateResult)]
        if json_output:
            console.print(
                json.dumps(
                    {
                        "status": "success",
                        "count": len(built),
                        "output": str(output),
                        "games": [_create_payload(item) for item in built],
                    }
                )
            )
            return
        console.print(format_batch(built, output))

    _guard(ctx, json_output, action)


@app.command()
def doctor(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show platform, assets, and key status. Keys are never printed."""
    del ctx
    report = _doctor_report()
    if json_output:
        console.print(json.dumps(report))
        return
    rows = [
        ("Platform", report["platform"]),
        ("Architecture", report["architecture"]),
        ("Python", report["python"]),
        ("libWiiPy", report["libwiipy"]),
        ("Rosetta", "yes" if report["rosetta"] else "no"),
        ("Assets", "OK" if report["assets"] == "ok" else "MISSING"),
        ("USB GX forwarder", "OK" if report["forwarder"] == "ok" else "MISSING"),
        ("Keys", report["keys"]),
        ("Output access", "OK" if report["output_access"] == "ok" else "FAIL"),
    ]
    for label, value in rows:
        console.print(f"{label:<18}{value}")


@assets_app.command("verify")
def assets_verify(ctx: typer.Context) -> None:
    """Check installed forwarders against the manifest."""

    def action() -> None:
        settings = load_config()
        rows = verify_installed(settings.assets_dir)
        failed = False
        for asset, status in rows:
            console.print(f"{asset.filename:<32}{status}")
            if asset.bootable and status != "ok":
                failed = True
        if failed:
            raise typer.Exit(code=3)

    _guard(ctx, False, action)


@assets_app.command("list")
def assets_list() -> None:
    """List the forwarders this version knows how to hash."""
    for asset in load_manifest().values():
        shipped = "yes" if asset.included else "no"
        bootable = "yes" if asset.bootable else "no"
        console.print(
            f"{asset.name}  {asset.filename}  {asset.source_device}  "
            f"sha256 {asset.sha256}  included {shipped}  bootable {bootable}"
        )


@assets_app.command("install")
def assets_install(
    ctx: typer.Context,
    source: Path = typer.Argument(..., help="A local USBLoaderGXForwarder DOL."),
) -> None:
    """Copy a local forwarder into the assets directory after its hash matches."""

    def action() -> None:
        settings = load_config()
        asset = install_asset(source, settings.assets_dir)
        console.print(f"Installed {asset.filename}")
        console.print(f"SHA-256 {asset.sha256}")

    _guard(ctx, False, action)


@wad_app.command("inspect")
def wad_inspect(
    ctx: typer.Context,
    wad: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Print the title ID, IOS, contents, and banner name of a WAD."""

    def action() -> None:
        validate_file(wad)
        info = describe_wad(wad.read_bytes())
        if json_output:
            console.print(json.dumps(info))
            return
        console.print(f"Title ID     {info['title_id']}")
        console.print(f"Channel ID   {info['channel_id']}")
        console.print(f"IOS          {info['ios']}")
        console.print(f"Version      {info['version']}")
        console.print(f"Boot index   {info['boot_index']}")
        console.print(f"Banner name  {info['banner_name']}")
        console.print(f"Game ID      {info['game_id'] or '-'}")
        console.print("Contents")
        contents = info["contents"]
        if isinstance(contents, list):
            for content in contents:
                console.print(
                    f"  {content['index']}  id {content['content_id']}  "
                    f"type {content['type']}  size {content['size']}  sha1 {content['sha1']}"
                )

    _guard(ctx, json_output, action)


def _create_payload(result: CreateResult) -> dict[str, object]:
    return {
        "status": "success",
        "game_id": result.game.game_id,
        "channel_id": result.channel_id,
        "loader": result.loader,
        "source": result.source,
        "output": str(result.output),
    }


def _doctor_report() -> dict[str, object]:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as package_version

    try:
        library = package_version("libWiiPy")
    except PackageNotFoundError:
        library = "unknown"
    try:
        settings = load_config()
        manifest_ok = bool(load_manifest()) and asset_for("usbloadergx", "usb").bootable
        installed = verify_installed(settings.assets_dir)
        forwarder_ok = all(status == "ok" for asset, status in installed if asset.bootable)
    except WiiShortcutError:
        manifest_ok = False
        forwarder_ok = False
    keys = key_status()
    output_ok = _output_writable()
    translated = _rosetta()
    system = "macOS" if platform.system() == "Darwin" else platform.system()
    ok = (
        manifest_ok and forwarder_ok and keys != "mismatch" and output_ok and translated is not True
    )
    return {
        "status": "ok" if ok else "attention",
        "ok": ok,
        "platform": system,
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "libwiipy": library,
        "rosetta": translated is True,
        "assets": "ok" if manifest_ok else "missing",
        "forwarder": "ok" if forwarder_ok else "missing",
        "keys": keys,
        "output_access": "ok" if output_ok else "fail",
    }


def _output_writable() -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=Path.cwd(), prefix=".wiishortcut-", delete=True):
            return True
    except OSError:
        return False


def _rosetta() -> bool | None:
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["sysctl", "-n", "sysctl.proc_translated"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    value = result.stdout.strip()
    if value == "1":
        return True
    if value == "0":
        return False
    return None
