from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import requests
from packaging.requirements import Requirement
from packaging.version import Version, InvalidVersion
from packaging.specifiers import SpecifierSet

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PackageRequest(BaseModel):
    packages: list[str]

metadata_cache = {}
CRITICAL_DEPS = {
    "numpy", "pandas", "cryptography", "pillow",
    "scipy", "torch", "tensorflow", "cffi",
    "pyopenssl", "lxml", "pycryptodome", "grpcio"
}

WHEEL_DIR = "offline_wheels"
os.makedirs(WHEEL_DIR, exist_ok=True)

@app.post("/get-wheels")
def get_wheels(req: PackageRequest):
    all_wheels = []
    seen = set()

    for entry in req.packages:
        name, version = parse_entry(entry)
        wheels = get_wheel_urls(name, version)
        for pkg_name, pkg_ver, url in wheels:
            if (pkg_name, pkg_ver, url) not in seen:
                wheel_path = download_wheel(url)
                all_wheels.append({"name": pkg_name, "version": pkg_ver, "url": url, "file": wheel_path})
                seen.add((pkg_name, pkg_ver, url))

    generate_requirements_txt(all_wheels)
    generate_install_script(all_wheels)
    return all_wheels

def parse_entry(entry):
    if "==" in entry:
        parts = entry.split("==")
        return parts[0].strip(), parts[1].strip()
    return entry.strip(), None

def fetch_metadata(package, version=None):
    key = f"{package}=={version}" if version else package
    if key in metadata_cache:
        return metadata_cache[key]

    try:
        res = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=10)
        res.raise_for_status()
    except requests.RequestException:
        return None

    data = res.json()
    chosen_version = version or data["info"]["version"]

    if version and version not in data["releases"]:
        chosen_version = data["info"]["version"]

    wheel_url = None
    for file in data["releases"].get(chosen_version, []):
        if file["packagetype"] == "bdist_wheel":
            wheel_url = file["url"]
            break

    requires_dist = data["info"].get("requires_dist", []) or []
    metadata = {
        "name": package,
        "version": chosen_version,
        "requires_dist": requires_dist,
        "wheel_url": wheel_url or "❌ No wheel found"
    }
    metadata_cache[key] = metadata
    return metadata

def resolve_version(package, specifier):
    try:
        res = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=10)
        res.raise_for_status()
        versions = res.json()["releases"].keys()
        spec = SpecifierSet(specifier or "")
        valid_versions = [v for v in versions if v in spec and is_valid_version(v)]
        return max(valid_versions, key=Version) if valid_versions else None
    except requests.RequestException:
        return None

def is_valid_version(v):
    try:
        Version(v)
        return True
    except InvalidVersion:
        return False

def parse_requirements(requirements):
    parsed = []
    for req in requirements:
        try:
            r = Requirement(req)
            parsed.append((r.name, str(r.specifier) if r.specifier else None))
        except Exception:
            continue
    return parsed

def get_wheel_urls(package, version=None):
    metadata = fetch_metadata(package, version)
    if not metadata:
        return []

    wheel_urls = []
    if "wheel_url" in metadata and "No wheel found" not in metadata["wheel_url"]:
        wheel_urls.append((metadata["name"], metadata["version"], metadata["wheel_url"]))

    for dep_name, dep_spec in parse_requirements(metadata['requires_dist']):
        dep_version = resolve_version(dep_name, dep_spec) if dep_spec else None
        dep_metadata = fetch_metadata(dep_name, dep_version)
        if dep_metadata and "wheel_url" in dep_metadata and "No wheel found" not in dep_metadata["wheel_url"]:
            wheel_urls.append((dep_name, dep_metadata["version"], dep_metadata["wheel_url"]))
            if dep_name.lower() in CRITICAL_DEPS:
                for sub_name, sub_spec in parse_requirements(dep_metadata['requires_dist']):
                    sub_version = resolve_version(sub_name, sub_spec)
                    sub_metadata = fetch_metadata(sub_name, sub_version)
                    if sub_metadata and "wheel_url" in sub_metadata and "No wheel found" not in sub_metadata["wheel_url"]:
                        wheel_urls.append((sub_name, sub_metadata["version"], sub_metadata["wheel_url"]))
    return wheel_urls

def download_wheel(url):
    local_filename = url.split("/")[-1]
    filepath = os.path.join(WHEEL_DIR, local_filename)
    if not os.path.exists(filepath):
        try:
            r = requests.get(url, stream=True, timeout=15)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as e:
            print(f"⚠️ Failed to download {url}: {e}")
    return filepath

def generate_requirements_txt(wheels):
    with open("requirements.txt", "w") as f:
        for pkg in wheels:
            f.write(f"{pkg['name']}=={pkg['version']}\n")

def generate_install_script(wheels):
    with open("install.sh", "w") as f:
        f.write("#!/bin/bash\n")
        f.write("echo 'Creating Conda environment...'\n")
        f.write("conda create -y -n offline_env python=3.9\n")
        f.write("conda activate offline_env || source activate offline_env\n")
        f.write("pip install --no-index --find-links=offline_wheels \\\n")
        for i, pkg in enumerate(wheels):
            sep = " \\\n" if i < len(wheels) - 1 else "\n"
            f.write(f"    {pkg['name']}=={pkg['version']}{sep}")
