# PyInstaller spec for the frozen JalRaksha backend (onedir).
#
#   JALRAKSHA_BUILD_VARIANT=cpu|gpu  pyinstaller desktop/backend/jalraksha-backend.spec \
#       --distpath desktop/build/backend-<variant> --workpath desktop/build/pyi-<variant>
#
# Normally run by desktop/scripts/build.mjs, which also creates the pinned venv.
#
# Choices that are NOT tuning — each one is a failure mode of a frozen build:
#
# * onedir, not onefile. Onefile unpacks the whole bundle to %TEMP% on every
#   launch — and on every run-worker and every solver pool process it spawns.
# * module_collection_mode "py" for jalraksha, jalraksha_service, compyle and
#   pysph: their .py SOURCES must exist on disk. Numba's cache=True kernels (32
#   of them) raise "no locator available" at import without a source file, and
#   compyle/PySPH call inspect.getsource on their own code.
# * paraview/ and tools/paraview/ are bundled as plain scripts at the same
#   relative paths: jalraksha_service.runtime.resource_root() resolves them
#   under sys._MEIPASS (render_static.py for pvpython, reservoir.py for tasks).
# * console=True. The desktop shell starts the exe hidden (windowsHide) and
#   captures its output into logs\; a windowed exe would have no stdout at all,
#   and uvicorn's logging and every print in the pipeline would fail or vanish.
# * The GPU variant adds numba-cuda (with its NVVM/NVRTC wheels) and pyopencl.
#   The CPU variant EXCLUDES them, so the capability probe reports numba.cuda
#   unavailable instead of claiming a GPU it cannot use. Neither variant bundles
#   an NVIDIA driver; the GPU path needs one installed on the machine.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

VARIANT = os.environ.get("JALRAKSHA_BUILD_VARIANT", "cpu").lower()
if VARIANT not in ("cpu", "gpu"):
    raise SystemExit(f"JALRAKSHA_BUILD_VARIANT must be cpu or gpu, not {VARIANT!r}")

REPO = Path(SPECPATH).resolve().parents[1]  # noqa: F821 - SPECPATH is injected by PyInstaller
SERVICE = REPO / "services" / "api"

datas, binaries, hiddenimports = [], [], []


def take(package):
    d, b, h = collect_all(package)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


for package in (
    "jalraksha", "jalraksha_service",
    "numba", "llvmlite", "scipy",
    "rasterio", "pyproj", "pyogrio", "shapely", "geopandas", "affine",
    "netCDF4", "cftime", "h5py", "xarray",
    "matplotlib", "PIL",
    "pysph", "compyle", "mako", "Cython",
    "ee", "google_auth_httplib2", "googleapiclient",
    "fastapi", "starlette", "pydantic", "uvicorn",
    "celery", "kombu", "billiard", "vine", "redis",
    "yaml", "requests", "tqdm",
):
    try:
        take(package)
    except Exception as exc:  # an optional dependency absent from this venv
        print(f"[spec] skipping {package}: {exc}")

hiddenimports += [
    "celery.loaders.app", "celery.backends.redis", "kombu.transport.redis",
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
]
hiddenimports += collect_submodules("jalraksha_service")

excludes = ["tkinter", "pytest", "IPython", "notebook", "jupyter"]
#: The NVIDIA CUDA Python stack, copied into the bundle as plain FILES at their
#: site-packages layout instead of through module analysis. Analysis cannot
#: follow it, and each attempt failed differently (all measured on this build):
#:   * numba-cuda replaces numba.cuda through a .pth import hook, so its modules
#:     are imported under names analysis never sees — the frozen probe loaded
#:     numba's legacy built-in numba.cuda and blamed the driver;
#:   * its C extensions and their delvewheel runtime (numba_cuda.libs) were
#:     dropped: "cannot import name '_typeconv'", then "DLL load failed";
#:   * `cuda` is a namespace package, so cuda.core's compiled modules were
#:     dropped too: "No module named 'cuda.core._utils.cuda_utils'".
#: On disk under _internal, the normal path-based importer loads them exactly as
#: from site-packages, and delvewheel's own add_dll_directory patches resolve.
GPU_RAW_TREES = ("numba_cuda", "numba_cuda.libs", "cuda", "cuda_bindings.libs",
                 "cuda_core.libs", "cuda_pathfinder", "nvidia")
GPU_RAW_FILES = ("_cuda_bindings_redirector.py", "_numba_cuda_redirector.py")

if VARIANT == "gpu":
    import numba as _numba

    _site = Path(_numba.__file__).resolve().parents[1]
    for _tree in GPU_RAW_TREES:
        _root = _site / _tree
        if not _root.is_dir():
            print(f"[spec] GPU tree {_tree} not installed; skipping")
            continue
        for _file in _root.rglob("*"):
            if not _file.is_file() or "__pycache__" in _file.parts:
                continue
            _dest = str(_file.parent.relative_to(_site))
            if _file.suffix.lower() in (".pyd", ".dll"):
                binaries.append((str(_file), _dest))
            else:
                datas.append((str(_file), _dest))
    for _name in GPU_RAW_FILES:
        if (_site / _name).is_file():
            datas.append((str(_site / _name), "."))
    # Their distribution metadata too: numba-cuda locates NVRTC/NVVM and checks
    # binding versions through importlib.metadata, which reads *.dist-info.
    for _info in _site.glob("*.dist-info"):
        if _info.name.lower().startswith(("numba_cuda-", "cuda_", "nvidia_")):
            for _file in _info.rglob("*"):
                if _file.is_file():
                    datas.append((str(_file), str(_file.parent.relative_to(_site))))
    # numba-cuda's extensions import a delvewheel-mangled msvcp140-<hash>.dll
    # from numba_cuda.libs, and numba_cuda has no add_dll_directory patch of its
    # own. Windows resolves an extension's dependencies from its own directory,
    # so the DLLs also go beside every numba-cuda extension.
    _ext_dirs = {str(p.parent.relative_to(_site)) for p in (_site / "numba_cuda").rglob("*.pyd")}
    for _dll in sorted((_site / "numba_cuda.libs").glob("*.dll")):
        for _dest in sorted(_ext_dirs):
            binaries.append((str(_dll), _dest))
    # Kept out of the module graph so no partial copy in the archive shadows the
    # files on disk.
    excludes += ["numba_cuda", "cuda", "cuda_bindings", "cuda_core", "cuda_pathfinder", "nvidia"]
    for package in ("pyopencl", "pytools", "platformdirs", "siphash24"):
        try:
            take(package)
        except Exception as exc:
            print(f"[spec] skipping {package}: {exc}")
else:
    excludes += ["numba_cuda", "cuda", "cuda_bindings", "cuda_core", "cuda_pathfinder",
                 "nvidia", "pyopencl"]

for rel in ("paraview", "tools/paraview"):
    for script in sorted((REPO / rel).glob("*.py")):
        datas.append((str(script), rel))

a = Analysis(  # noqa: F821
    [str(Path(SPECPATH) / "jalraksha_backend.py")],  # noqa: F821
    pathex=[str(REPO), str(SERVICE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    excludes=excludes,
    module_collection_mode={
        "jalraksha": "py",
        "jalraksha_service": "py",
        "compyle": "py",
        "pysph": "py+pyz",
        "numba_cuda": "py+pyz",
    },
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="jalraksha-backend",
    console=True,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe, a.binaries, a.datas,
    name="jalraksha-backend",
    upx=False,
)
