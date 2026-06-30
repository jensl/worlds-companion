import argparse
import os
import sys
import uvicorn

def install_startup(args: argparse.Namespace, instances_path: str) -> None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        print("Error: APPDATA environment variable not found. Windows startup folder could not be determined.")
        sys.exit(1)

    startup_dir = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    if not os.path.isdir(startup_dir):
        print(f"Error: Startup directory does not exist: {startup_dir}")
        sys.exit(1)

    vbs_path = os.path.join(startup_dir, "companion.vbs")

    escaped_instances_path = instances_path.replace('"', '""')
    command = (
        f'uv tool run --from git+https://github.com/jensl/worlds-companion.git companion serve '
        f'--host {args.host} --port {args.port} --instances-dir "{escaped_instances_path}"'
    )

    vbs_content = (
        f'Set WshShell = CreateObject("WScript.Shell")\n'
        f'WshShell.Run "{command.replace('"', '""')}", 0, False\n'
    )

    try:
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        print(f"Successfully installed startup script to: {vbs_path}")
        print("The companion daemon will now run automatically in the background when you log in to Windows.")
    except Exception as e:
        print(f"Error: Failed to write startup script to {vbs_path}: {e}")
        sys.exit(1)

def main() -> None:
    # If no subcommand is specified, or arguments only contain options, default to "serve"
    # to maintain backward compatibility.
    if len(sys.argv) < 2 or (sys.argv[1].startswith("-") and sys.argv[1] not in ("-h", "--help")):
        sys.argv.insert(1, "serve")

    parser = argparse.ArgumentParser(description="Curseforge Companion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Sub-commands")

    # Serve sub-command
    serve_parser = subparsers.add_parser("serve", help="Run the companion daemon")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    serve_parser.add_argument("--port", type=int, default=18181, help="Port to listen on")
    serve_parser.add_argument("--instances-dir", default="~/curseforge/minecraft/Instances", help="Path to Curseforge instances folder")

    # Install sub-command
    install_parser = subparsers.add_parser("install", help="Install the companion to run automatically on Windows startup")
    install_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind for the startup service")
    install_parser.add_argument("--port", type=int, default=18181, help="Port to listen on for the startup service")
    install_parser.add_argument("--instances-dir", default="~/curseforge/minecraft/Instances", help="Path to Curseforge instances folder for the startup service")

    args = parser.parse_args()

    instances_path = os.path.abspath(os.path.expanduser(args.instances_dir))
    os.environ["COMPANION_INSTANCES_DIR"] = instances_path

    if args.command == "serve":
        print(f"Starting companion daemon on http://{args.host}:{args.port}")
        print(f"Curseforge Instances path: {instances_path}")
        uvicorn.run("companion.app:app", host=args.host, port=args.port, reload=False)
    elif args.command == "install":
        install_startup(args, instances_path)

