from fastapi import HTTPException
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import requests
import tarfile
import shutil
from packaging.requirements import Requirement
from packaging.version import Version, InvalidVersion
from packaging.specifiers import SpecifierSet
from typing import List, Dict, Set, Tuple, Optional
import subprocess
import json
import sys
import logging

app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PackageRequest(BaseModel):
    packages: List[str]
    python_version: str = "3.9"  # Default Python version
    env_name: str = "offline_env"  # Default environment name


# Constants
CRITICAL_DEPS = {
    "numpy", "pandas", "cryptography", "pillow",
    "scipy", "torch", "tensorflow", "cffi",
    "pyopenssl", "lxml", "pycryptodome", "grpcio",
    "setuptools", "pip", "wheel"  # Essential build tools
}
WHEEL_DIR = "offline_wheels"
ENV_DIR = "conda_envs"
os.makedirs(WHEEL_DIR, exist_ok=True)
os.makedirs(ENV_DIR, exist_ok=True)

# Cache for package metadata
metadata_cache: Dict[str, Dict] = {}


@app.get("/get-python-versions")
async def get_python_versions():
    """Fetch stable Python versions from conda's metadata"""
    try:
        # Fetch from conda's metadata (official source)
        response = requests.get(
            "https://raw.githubusercontent.com/conda/conda/main/conda/base/constants.py", timeout=5)
        response.raise_for_status()

        # Parse versions from the constants file
        content = response.text
        versions = []

        # Extract stable versions (this parses conda's constant definitions)
        for line in content.split('\n'):
            if line.startswith('DEFAULT_PYTHON_VERSION'):
                current_stable = line.split('=')[1].strip().strip("'")
                versions.append(current_stable)
            elif line.startswith('SUPPORTED_PYTHON_VERSIONS'):
                versions.extend(
                    v.strip().strip("'")
                    for v in line.split('=')[1].strip()[1:-1].split(',')
                )

        # Remove duplicates and sort (newest first)
        versions = sorted(
            list(set(versions)),
            key=lambda v: tuple(map(int, v.split('.'))),
            reverse=True
        )

        return {
            "versions": versions,
            "recommended": versions[0]  # Newest stable version
        }

    except Exception as e:
        # Fallback to hardcoded versions if API fails
        versions = ["3.12", "3.11", "3.10", "3.9", "3.8"]
        return {
            "versions": versions,
            "recommended": versions[0],
            "warning": f"Failed to fetch live versions: {str(e)}"
        }


@app.post("/get-wheels")
async def get_wheels(req: PackageRequest):
    """Endpoint to fetch wheel files for specified packages and their dependencies."""
    all_wheels = []
    seen_packages: Set[Tuple[str, str]] = set()

    try:
        for entry in req.packages:
            name, version_spec = parse_entry(entry)
            wheels = await get_wheel_urls(name, version_spec)

            for pkg_name, pkg_ver, url in wheels:
                if (pkg_name, pkg_ver) not in seen_packages:
                    wheel_path = download_wheel(url)
                    if wheel_path:
                        all_wheels.append({
                            "name": pkg_name,
                            "version": pkg_ver,
                            "url": url,
                            "file": os.path.basename(wheel_path)
                        })
                        seen_packages.add((pkg_name, pkg_ver))

        if all_wheels:
            generate_requirements_txt(all_wheels)
            generate_install_script(all_wheels, ".")

        return {"wheels": all_wheels, "status": "success"}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process package dependencies: {str(e)}"
        )


def check_conda_available():
    try:
        result = subprocess.run(["conda", "--version"], check=True, capture_output=True, text=True)
        logger.info(f"Conda version: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Conda check failed: {str(e)}")
        return False


@app.post("/create-offline-environment")
async def create_offline_environment(req: PackageRequest):
    """Create a complete portable Conda environment with all dependencies."""
    if not check_conda_available():
        raise HTTPException(
            status_code=400,
            detail="Conda is not available in system PATH. Please install Anaconda/Miniconda first."
        )

    try:
        # Step 1: Download all required wheels
        all_wheels = []
        seen_packages: Set[Tuple[str, str]] = set()

        # Add essential packages if not already included
        required_packages = req.packages.copy()
        for essential in ["pip", "setuptools", "wheel"]:
            if not any(pkg.split('==')[0].lower() == essential for pkg in required_packages):
                required_packages.append(essential)

        for entry in required_packages:
            name, version_spec = parse_entry(entry)
            wheels = await get_wheel_urls(name, version_spec)

            for pkg_name, pkg_ver, url in wheels:
                if (pkg_name, pkg_ver) not in seen_packages:
                    wheel_path = download_wheel(url)
                    if wheel_path:
                        all_wheels.append({
                            "name": pkg_name,
                            "version": pkg_ver,
                            "url": url,
                            "file": os.path.basename(wheel_path)
                        })
                        seen_packages.add((pkg_name, pkg_ver))

        if not all_wheels:
            raise HTTPException(
                status_code=400, detail="No wheels were downloaded")

        # Step 2: Create Conda environment
        env_path = os.path.join(ENV_DIR, req.env_name)
        if os.path.exists(env_path):
            logger.info(f"Removing existing environment at {env_path}")
            shutil.rmtree(env_path)

        # Create the environment with minimal packages
        create_cmd = [
            "conda", "create",
            "--prefix", env_path,
            f"python={req.python_version}",
            "--yes", "--quiet", "--offline",
            "pip", "setuptools", "wheel"
        ]
        
        logger.info(f"Creating conda environment with command: {' '.join(create_cmd)}")
        result = subprocess.run(create_cmd, check=True, capture_output=True, text=True)
        logger.info(f"Conda create output: {result.stdout}")
        if result.stderr:
            logger.warning(f"Conda create errors: {result.stderr}")

        # Step 3: Generate and run installation script
        generate_requirements_txt(all_wheels)
        generate_install_script(all_wheels, ".")

        # Copy wheels to environment's directory
        env_wheel_dir = os.path.join(env_path, "wheels")
        os.makedirs(env_wheel_dir, exist_ok=True)
        for wheel in os.listdir(WHEEL_DIR):
            if wheel.endswith(".whl"):
                shutil.copy2(os.path.join(WHEEL_DIR, wheel), env_wheel_dir)

        # Create a more robust installation script inside the environment
        install_script_content = f"""#!/bin/bash
echo "Installing packages in offline mode..."
export PIP_NO_INDEX=1
export PIP_FIND_LINKS={env_wheel_dir}
for wheel in {env_wheel_dir}/*.whl; do
    echo "Installing $wheel..."
    pip install --no-deps "$wheel" || echo "Failed to install $wheel"
done
echo "Installation complete"
"""
        
        install_script_path = os.path.join(env_path, "install_packages.sh")
        with open(install_script_path, "w") as f:
            f.write(install_script_content)
        os.chmod(install_script_path, 0o755)

        # Run the installation script
        install_cmd = [
            "conda", "run", "--no-capture-output", "--prefix", env_path,
            "bash", os.path.join(env_path, "install_packages.sh")
        ]
        
        logger.info(f"Running installation with command: {' '.join(install_cmd)}")
        install_result = subprocess.run(install_cmd, capture_output=True, text=True)
        logger.info(f"Installation output: {install_result.stdout}")
        if install_result.stderr:
            logger.error(f"Installation errors: {install_result.stderr}")
        
        if install_result.returncode != 0:
            raise subprocess.CalledProcessError(
                install_result.returncode, install_cmd, install_result.stdout, install_result.stderr)

        # Step 4: Package the environment for portability
        archive_path = package_environment(env_path, req.env_name)

        return {
            "status": "success",
            "environment": req.env_name,
            "python_version": req.python_version,
            "archive_path": archive_path,
            "wheels": all_wheels
        }

    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed: {e.cmd}\nReturn code: {e.returncode}\nOutput: {e.stdout}\nError: {e.stderr}"
        logger.error(error_msg)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create Conda environment: {error_msg}"
        )
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create offline environment: {str(e)}"
        )


def package_environment(env_path: str, env_name: str) -> str:
    """Package the Conda environment for portability"""
    archive_path = os.path.join(ENV_DIR, f"{env_name}.tar.gz")
    
    logger.info(f"Packaging environment from {env_path} to {archive_path}")

    # Make sure the environment exists
    if not os.path.exists(env_path):
        raise FileNotFoundError(f"Environment path {env_path} does not exist")

    # Create the archive
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(env_path, arcname=os.path.basename(env_path))
        
        logger.info(f"Successfully created archive at {archive_path}")
        return archive_path
    except Exception as e:
        logger.error(f"Failed to create archive: {str(e)}")
        raise


def parse_entry(entry: str) -> Tuple[str, Optional[str]]:
    """Parse package entry into name and version specifier."""
    entry = entry.strip()
    if "==" in entry:
        parts = entry.split("==", 1)
        return parts[0].strip(), parts[1].strip()
    elif any(op in entry for op in [">=", "<=", "~=", "!="]):
        try:
            req = Requirement(entry)
            return req.name, str(req.specifier) if req.specifier else None
        except Exception:
            return entry, None
    return entry, None


async def fetch_metadata(package: str, version_spec: Optional[str] = None) -> Optional[dict]:
    """Fetch package metadata from PyPI with caching."""
    package = package.lower()  # PyPI packages are case-insensitive
    key = f"{package}=={version_spec}" if version_spec else package

    if key in metadata_cache:
        return metadata_cache[key]

    try:
        res = requests.get(f"https://pypi.org/pypi/{package}/json", timeout=10)
        res.raise_for_status()
        data = res.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch metadata for {package}: {e}")
        return None

    versions = list(data["releases"].keys())
    valid_versions = []

    for v in versions:
        try:
            Version(v)
            valid_versions.append(v)
        except InvalidVersion:
            continue

    if version_spec:
        try:
            spec = SpecifierSet(version_spec)
            matching_versions = [
                v for v in valid_versions if Version(v) in spec]
            if not matching_versions:
                logger.warning(f"No version matching {version_spec} for {package}")
                return None
            chosen_version = max(matching_versions, key=Version)
        except Exception as e:
            logger.warning(f"Invalid version specifier {version_spec} for {package}: {e}")
            chosen_version = data["info"]["version"]
    else:
        chosen_version = data["info"]["version"]

    if not chosen_version:
        return None

    # Find the best wheel (prefer manylinux)
    wheel_url = None
    for file in data["releases"].get(chosen_version, []):
        if file["packagetype"] == "bdist_wheel":
            if not wheel_url or "manylinux" in file["filename"].lower():
                wheel_url = file["url"]
                if "manylinux" in file["filename"].lower():  # Found optimal wheel
                    break

    metadata = {
        "name": package,
        "version": chosen_version,
        "requires_dist": [
            req for req in (data["info"].get("requires_dist") or [])
            if "extra ==" not in req  # Skip optional dependencies
        ],
        "wheel_url": wheel_url
    }

    metadata_cache[key] = metadata
    return metadata


async def get_wheel_urls(package: str, version_spec: Optional[str] = None) -> List[Tuple[str, str, str]]:
    """Get wheel URLs for a package and its dependencies."""
    metadata = await fetch_metadata(package, version_spec)
    if not metadata or not metadata.get("wheel_url"):
        logger.warning(f"No wheel found for {package} {version_spec if version_spec else ''}")
        return []

    wheel_urls = [
        (metadata["name"], metadata["version"], metadata["wheel_url"])]

    # Process direct dependencies
    for req_str in metadata["requires_dist"]:
        try:
            req = Requirement(req_str)
            dep_name = req.name
            dep_spec = str(req.specifier) if req.specifier else None

            # Skip if this is a critical dependency we already handle specially
            if dep_name.lower() in CRITICAL_DEPS:
                continue

            dep_metadata = await fetch_metadata(dep_name, dep_spec)
            if dep_metadata and dep_metadata.get("wheel_url"):
                wheel_urls.append(
                    (dep_metadata["name"], dep_metadata["version"], dep_metadata["wheel_url"]))
        except Exception as e:
            logger.warning(f"Failed to process dependency {req_str}: {e}")

    # Handle critical dependencies with their latest versions
    for crit_dep in CRITICAL_DEPS:
        if crit_dep.lower() != package.lower():  # Don't re-add the main package
            crit_metadata = await fetch_metadata(crit_dep)
            if crit_metadata and crit_metadata.get("wheel_url"):
                wheel_urls.append(
                    (crit_metadata["name"], crit_metadata["version"], crit_metadata["wheel_url"]))

    return wheel_urls


def download_wheel(url: str) -> Optional[str]:
    """Download wheel file if it doesn't already exist."""
    try:
        local_filename = url.split("/")[-1]
        filepath = os.path.join(WHEEL_DIR, local_filename)

        if os.path.exists(filepath):
            logger.info(f"Wheel already exists: {local_filename}")
            return filepath

        logger.info(f"Downloading {url}")
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:  # Filter out keep-alive chunks
                        f.write(chunk)
        logger.info(f"Downloaded wheel to {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"⚠️ Failed to download {url}: {e}")
        return None


def generate_requirements_txt(wheels: List[dict]):
    """Generate requirements.txt file from collected wheels."""
    requirements_path = os.path.join(WHEEL_DIR, "requirements.txt")
    with open(requirements_path, "w") as f:
        for pkg in wheels:
            f.write(f"{pkg['name']}=={pkg['version']}\n")
    logger.info(f"Generated requirements.txt at {requirements_path}")


def generate_install_script(wheels: List[dict], env_path: str):
    """Generate installation scripts for both Unix and Windows environments."""
    # --- Linux/macOS (.sh script) ---
    sh_script_path = os.path.join(WHEEL_DIR, "install.sh")
    with open(sh_script_path, "w", newline="\n") as f:
        f.write("#!/bin/bash\n")
        f.write("echo 'Installing packages in offline mode...'\n")
        f.write("cd \"$(dirname \"$0\")\" || exit 1\n")
        f.write("export PIP_NO_INDEX=1\n")
        f.write("export PIP_FIND_LINKS=$PWD\n")
        f.write("for whl in *.whl; do\n")
        f.write("  echo \"Installing $whl\"\n")
        f.write("  pip install --no-deps \"$whl\" || echo \"Failed to install $whl\"\n")
        f.write("done\n")
    os.chmod(sh_script_path, 0o755)
    logger.info(f"Created install script: {sh_script_path}")

    # --- Windows (.bat script) ---
    bat_script_path = os.path.join(WHEEL_DIR, "install.bat")
    with open(bat_script_path, "w", newline="\r\n") as f:
        f.write("@echo off\n")
        f.write("echo Installing packages in offline mode...\n")
        f.write("cd /d %~dp0\n")
        f.write("set PIP_NO_INDEX=1\n")
        f.write("set PIP_FIND_LINKS=%cd%\n")
        f.write("for %%f in (*.whl) do (\n")
        f.write("    echo Installing %%f\n")
        f.write("    pip install --no-deps %%f || echo Failed to install %%f\n")
        f.write(")\n")
    logger.info(f"Created install script: {bat_script_path}")


def is_valid_version(v: str) -> bool:
    """Check if a version string is valid."""
    try:
        Version(v)
        return True
    except InvalidVersion:
        return False