from signal import signal
from typing import Literal
from typing import TypedDict
from dataclasses import dataclass
import json
import os
import tempfile
import logging
import zipfile
import sys
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List, Dict, Any

app = FastAPI(title="Curseforge Companion Daemon")

# Enable CORS for frontend web apps to connect on localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

API_VERSION = "1"


@app.get("/version")
def get_version():
    return {"apiVersion": API_VERSION}


def get_instances_dir() -> str:
    path = os.environ.get("COMPANION_INSTANCES_DIR")
    if not path:
        path = os.path.expanduser("~/curseforge/minecraft/Instances")
    return os.path.abspath(path)


def read_instance_json(instance_dir: str) -> dict[str, Any] | None:
    instance_json_path = os.path.join(instance_dir, "minecraftinstance.json")

    if not os.path.isfile(instance_json_path):
        logger.warning(f"No such file: {instance_json_path}")
        return None

    try:
        with open(instance_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading JSON from {instance_json_path}: {e}")
        return None


@dataclass
class Profile:
    name: str
    minecraft_version: str  # e.g. "26.2"
    mod_loader: str | None  # e.g. "forge-65.0.1"
    mods_count: int

    data: dict[str, Any]

    @staticmethod
    def read(instance_dir: str) -> Profile | None:
        logger.info(f"Reading profile in {instance_dir}")

        data = read_instance_json(instance_dir)
        if data is None:
            return None

        profile_name = data.get("name")
        minecraft_version = data.get("gameVersion")
        base_mod_loader = data.get("baseModLoader")
        mods_count = 0

        if base_mod_loader:
            mod_loader = base_mod_loader.get("name", None)
            if mod_loader and mod_loader.endswith(f"-{minecraft_version}"):
                mod_loader = mod_loader.rpartition("-")[0]
            # Count mod JAR files
            mods_dir = os.path.join(instance_dir, "mods")
            if os.path.isdir(mods_dir):
                for f_name in os.listdir(mods_dir):
                    if f_name.lower().endswith(".jar") and os.path.isfile(
                        os.path.join(mods_dir, f_name)
                    ):
                        mods_count += 1
        else:
            mod_loader = None

        return Profile(profile_name, minecraft_version, mod_loader, mods_count, data)


@app.get("/profiles")
def list_profiles() -> List[Dict[str, Any]]:
    instances_dir = get_instances_dir()
    if not os.path.isdir(instances_dir):
        return []

    logger.info(f"Listing profiles in {instances_dir}")

    profiles = []
    try:
        for entry in os.listdir(instances_dir):
            logger.info(f"Looking at {entry}")

            if profile := Profile.read(os.path.join(instances_dir, entry)):
                profiles.append(
                    {
                        "id": entry,
                        "name": profile.name,
                        "minecraftVersion": profile.minecraft_version,
                        "modLoader": profile.mod_loader,
                        "modsCount": profile.mods_count,
                    }
                )
    except Exception as e:
        print(f"Error listing instances directory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return profiles


def remove_temp_file(path: str):
    try:
        os.unlink(path)
    except Exception as e:
        print(f"Failed to remove temp file {path}: {e}")


@app.get("/profiles/{profile_id}/manifest")
def get_profile_manifest(profile_id: str):
    instances_dir = get_instances_dir()
    target_dir = os.path.abspath(os.path.join(instances_dir, profile_id))

    # Traversal security check
    if not target_dir.startswith(instances_dir):
        raise HTTPException(status_code=400, detail="Invalid profile ID")

    if not os.path.isdir(target_dir):
        raise HTTPException(status_code=404, detail="Profile not found")

    return render_manifest(Profile.read(target_dir))


@app.get("/profiles/{profile_id}/download")
def download_profile(profile_id: str, background_tasks: BackgroundTasks):
    instances_dir = get_instances_dir()
    target_dir = os.path.abspath(os.path.join(instances_dir, profile_id))

    # Traversal security check
    if not target_dir.startswith(instances_dir):
        raise HTTPException(status_code=400, detail="Invalid profile ID")

    if not os.path.isdir(target_dir):
        raise HTTPException(status_code=404, detail="Profile not found")

    profile = Profile.read(target_dir)
    manifest = render_manifest(profile)

    # Create temporary zip archive
    try:
        temp_fd, temp_zip_path = tempfile.mkstemp(suffix=".zip")
        os.close(temp_fd)  # Close file descriptor so zipfile can open it

        with zipfile.ZipFile(temp_zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            # Write manifest.json
            z.writestr("manifest.json", json.dumps(manifest, indent=2))

            # Write mods folder files
            mods_dir = os.path.join(target_dir, "mods")
            if os.path.isdir(mods_dir):
                for filename in os.listdir(mods_dir):
                    filepath = os.path.join(mods_dir, filename)
                    if os.path.isfile(filepath) and filename.lower().endswith(".jar"):
                        z.write(filepath, arcname=os.path.join("mods", filename))
    except Exception as e:
        if os.path.exists(temp_zip_path):
            remove_temp_file(temp_zip_path)
        raise HTTPException(status_code=500, detail=f"Failed to build ZIP archive: {e}")

    # Set up background task to delete the temporary file after delivery
    background_tasks.add_task(remove_temp_file, temp_zip_path)

    safe_filename = f"{profile_id.replace(' ', '_')}.zip"
    return FileResponse(
        path=temp_zip_path, media_type="application/zip", filename=safe_filename
    )


@app.post("/restart")
def restart():
    logger.info("Restarting daemon...")

    def self_destruct():
        import time

        time.sleep(0.5)
        # Exit with a special code (100) indicating a restart request
        os._exit(100)

    import threading

    threading.Thread(target=self_destruct, daemon=True).start()
    return {"status": "restarting"}


class ManifestFile(TypedDict):
    projectID: int
    fileID: int
    required: bool
    isLocked: bool


class ManifestModLoader(TypedDict):
    id: str
    primary: bool


class ManifestMinecraft(TypedDict):
    version: str
    modLoaders: list[ManifestModLoader]


class Manifest(TypedDict):
    minecraft: ManifestMinecraft
    manifestType: Literal["minecraftModpack"]
    manifestVerison: Literal[1]
    name: str
    version: str
    author: str
    files: list[ManifestFile]


def render_manifest(profile: Profile) -> Manifest:
    return {
        "minecraft": {
            "version": profile.minecraft_version,
            "modLoaders": [{"id": profile.mod_loader, "primary": True}],
        },
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": profile.name,
        "version": "",
        "author": "",
        "files": [
            render_manifest_file(installed_addon)
            for installed_addon in profile.data.get("installedAddons", [])
        ],
    }


def render_manifest_file(addon: dict[str, Any]) -> ManifestFile:
    return {
        "projectID": addon["addonID"],
        "fileID": addon["installedFile"]["id"],
        "required": True,
        "isLocked": False,
    }
