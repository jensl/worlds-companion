import json
import os
import tempfile
import zipfile
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


def get_instances_dir() -> str:
    path = os.environ.get("COMPANION_INSTANCES_DIR")
    if not path:
        path = os.path.expanduser("~/curseforge/minecraft/Instances")
    return os.path.abspath(path)


@app.get("/profiles")
def list_profiles() -> List[Dict[str, Any]]:
    instances_dir = get_instances_dir()
    if not os.path.isdir(instances_dir):
        return []

    profiles = []
    try:
        for entry in os.listdir(instances_dir):
            entry_path = os.path.join(instances_dir, entry)
            if not os.path.isdir(entry_path):
                continue

            instance_json_path = os.path.join(entry_path, "minecraftinstance.json")
            if not os.path.isfile(instance_json_path):
                continue

            try:
                with open(instance_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Error loading JSON from {instance_json_path}: {e}")
                continue

            manifest = data.get("manifest")

            # Extract basic details
            profile_name = entry
            minecraft_version = "Unknown"
            mod_loader = None

            if manifest and isinstance(manifest, dict):
                profile_name = manifest.get("name", entry)
                mc_info = manifest.get("minecraft", {})
                minecraft_version = mc_info.get("version", "Unknown")
                mod_loaders = mc_info.get("modLoaders", [])
                if mod_loaders and isinstance(mod_loaders, list):
                    mod_loader = mod_loaders[0].get("id")
            else:
                profile_name = data.get("name", entry)
                minecraft_version = data.get("gameVersion", "Unknown")
                base_loader = data.get("baseModLoader")
                if base_loader and isinstance(base_loader, dict):
                    mod_loader = base_loader.get("name")

            # Count mod JAR files
            mods_count = 0
            mods_dir = os.path.join(entry_path, "mods")
            if os.path.isdir(mods_dir):
                for f_name in os.listdir(mods_dir):
                    if f_name.lower().endswith(".jar") and os.path.isfile(
                        os.path.join(mods_dir, f_name)
                    ):
                        mods_count += 1

            profiles.append(
                {
                    "id": entry,
                    "name": profile_name,
                    "minecraftVersion": minecraft_version,
                    "modLoader": mod_loader,
                    "modsCount": mods_count,
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


@app.get("/profiles/{profile_id}/download")
def download_profile(profile_id: str, background_tasks: BackgroundTasks):
    instances_dir = get_instances_dir()
    target_dir = os.path.abspath(os.path.join(instances_dir, profile_id))

    # Traversal security check
    if not target_dir.startswith(instances_dir):
        raise HTTPException(status_code=400, detail="Invalid profile ID")

    if not os.path.isdir(target_dir):
        raise HTTPException(status_code=404, detail="Profile not found")

    instance_json_path = os.path.join(target_dir, "minecraftinstance.json")
    if not os.path.isfile(instance_json_path):
        raise HTTPException(
            status_code=404, detail="minecraftinstance.json not found in profile"
        )

    try:
        with open(instance_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read minecraftinstance.json: {e}"
        )

    manifest = data.get("manifest")

    # Synthesize manifest if it is null
    if not manifest or not isinstance(manifest, dict):
        base_loader = data.get("baseModLoader")
        loaders_list = []
        if base_loader and isinstance(base_loader, dict) and base_loader.get("name"):
            loaders_list.append({"id": base_loader.get("name"), "primary": True})

        manifest = {
            "minecraft": {
                "version": data.get("gameVersion", "Unknown"),
                "modLoaders": loaders_list,
            },
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": data.get("name", profile_id),
            "version": "1.0",
            "author": data.get("customAuthor") or "User",
            "files": [],
        }

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
