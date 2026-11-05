{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.aurora;
in
{
  options.programs.aurora = {
    enable = lib.mkEnableOption "Aurora, a configuration tool for the EvoFox Blaze mouse";
    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "aurora";
      description = "The Aurora package to use.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ cfg.package ];
    # Install the udev rule that lets the logged in user open the mouse.
    services.udev.packages = [ cfg.package ];
  };
}
