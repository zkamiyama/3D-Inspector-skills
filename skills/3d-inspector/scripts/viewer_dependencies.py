"""Known conversion-only dependencies, installed by the one-command launcher on demand."""
OPTIONAL = {'OpenCASCADE': (80, 'cadquery-ocp-novtk>=7.8.1.1,<8', 'import OCP'),
            'usd-core': (78, 'usd-core>=24.3', 'from pxr import Usd, UsdGeom'),
            'DracoPy': (79, 'DracoPy>=2.2,<3', 'import DracoPy')}


class MissingViewerDependency(ImportError):
    def __init__(self, package):
        self.status, requirement, _ = OPTIONAL[package]
        super().__init__(f'This model needs {requirement}. Run view.py to install it automatically.')
