{
  lib,
  python3Packages,
}:

python3Packages.buildPythonApplication {
  pname = "aurora";
  version = "0.1.0";
  src = lib.cleanSource ../.;
  pyproject = true;

  build-system = [ python3Packages.setuptools ];

  nativeCheckInputs = [ python3Packages.pytestCheckHook ];

  postInstall = ''
    install -Dm644 udev/70-aurora.rules $out/lib/udev/rules.d/70-aurora.rules
  '';

  pythonImportsCheck = [ "aurora" ];

  meta = {
    description = "Configure the EvoFox Blaze mouse from Linux";
    homepage = "https://github.com/rugbedbugg/aurora";
    license = lib.licenses.wtfpl;
    mainProgram = "aurora";
    platforms = lib.platforms.linux;
  };
}
