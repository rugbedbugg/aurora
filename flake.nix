{
  description = "Configure the EvoFox Blaze mouse from Linux";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAll (pkgs: rec {
        blazectl = pkgs.callPackage ./nix/package.nix { };
        default = blazectl;
      });

      overlays.default = final: _prev: {
        blazectl = final.callPackage ./nix/package.nix { };
      };

      nixosModules.default = ./nix/module.nix;

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          inputsFrom = [ self.packages.${pkgs.stdenv.hostPlatform.system}.blazectl ];
          packages = [
            pkgs.python3Packages.pytest
            pkgs.ruff
          ];
        };
      });

      formatter = forAll (pkgs: pkgs.nixfmt);
    };
}
