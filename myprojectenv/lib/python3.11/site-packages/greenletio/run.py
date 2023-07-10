import asyncio
import importlib
import os
import sys
import greenletio


def import_path(path):
    module_name = os.path.basename(path).replace('-', '_')
    spec = importlib.util.spec_from_loader(
        module_name,
        importlib.machinery.SourceFileLoader(module_name, path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[module_name] = module
    return module


@greenletio.async_
def main():
    with greenletio.patch_blocking():
        import_path(sys.argv[0])


if __name__ == '__main__':
    sys.argv = sys.argv[1:]
    asyncio.run(main())
