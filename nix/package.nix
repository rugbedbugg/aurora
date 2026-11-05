{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "blazectl";
  version = "0.1.0";
  src = lib.cleanSource ../.;
  pyproject = true;

  build-system = [ python3Packages.setuptools ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  postInstall = ''
    install -Dm644 udev/70-blazectl.rules $out/lib/udev/rules.d/70-blazectl.rules
  '';

  pythonImportsCheck = [ "blazectl" ];

  meta = {
    description = "Configure the EvoFox Blaze mouse from Linux";
    homepage = "https://github.com/rugbedbugg/blazectl";
    license = lib.licenses.wtfpl;
    mainProgram = "blazectl";
    platforms = lib.platforms.linux;
  };
}
