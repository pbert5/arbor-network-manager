{ config, lib, pkgs, ... }:
let
  cfg = config.services.arbor-networkd;
  package = pkgs.python3Packages.buildPythonPackage {
    pname = "arbor-network-manager";
    version = "0.1.0";
    src = ./.;
    pyproject = true;
    build-system = [ pkgs.python3Packages.setuptools ];
  };
in
{
  options.services.arbor-networkd = {
    enable = lib.mkEnableOption "Arbor network manager daemon";
    package = lib.mkOption {
      type = lib.types.package;
      default = package;
      description = "Network manager package providing arbor-networkd.";
    };
    registrySnapshot = lib.mkOption {
      type = lib.types.path;
      description = "Accepted Registry network snapshot JSON file.";
    };
    socket = lib.mkOption {
      type = lib.types.str;
      default = "/run/arbor/networkd.sock";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.arbor-networkd = {
      description = "Arbor network manager";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        ExecStart = "${cfg.package}/bin/arbor-networkd --registry-snapshot ${cfg.registrySnapshot} --socket ${cfg.socket}";
        DynamicUser = true;
        RuntimeDirectory = "arbor";
        Restart = "on-failure";
        RestartSec = 2;
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "strict";
        ReadOnlyPaths = [ cfg.registrySnapshot ];
      };
    };
  };
}
