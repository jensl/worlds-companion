import argparse
import os
import uvicorn

def main() -> None:
    parser = argparse.ArgumentParser(description="Curseforge Companion Daemon")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=18181, help="Port to listen on")
    parser.add_argument("--instances-dir", default="~/curseforge/minecraft/Instances", help="Path to Curseforge instances folder")
    args = parser.parse_args()

    instances_path = os.path.abspath(os.path.expanduser(args.instances_dir))
    os.environ["COMPANION_INSTANCES_DIR"] = instances_path

    print(f"Starting companion daemon on http://{args.host}:{args.port}")
    print(f"Curseforge Instances path: {instances_path}")
    uvicorn.run("companion.app:app", host=args.host, port=args.port, reload=False)
