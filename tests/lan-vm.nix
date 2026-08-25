{ pkgs, networkManagerPackage, ... }:
pkgs.testers.runNixOSTest {
  name = "arbor-network-lan-ssh";
  nodes = {
    target = { ... }: {
      virtualisation.vlans = [ 100 ];
      networking.hostName = "target";
      networking.interfaces.eth1.ipv4.addresses = [{ address = "192.168.100.2"; prefixLength = 24; }];
      services.openssh.enable = true;
      users.users.root.openssh.authorizedKeys.keys = [ "ssh-ed25519 AAAATEST" ];
      services.openssh.settings.PasswordAuthentication = false;
    };
    source = { ... }: {
      imports = [ ../nixos-module.nix ];
      virtualisation.vlans = [ 100 ];
      networking.hostName = "source";
      networking.interfaces.eth1.ipv4.addresses = [{ address = "192.168.100.1"; prefixLength = 24; }];
      environment.systemPackages = [ networkManagerPackage pkgs.jq pkgs.socat ];
      systemd.services.lan-provider = {
        wantedBy = [ "multi-user.target" ];
        serviceConfig = {
          ExecStart = "${networkManagerPackage}/bin/arbor-network-provider-lan --node source --interface eth1 --socket /run/arbor/lan.sock";
          RuntimeDirectory = "arbor";
          Restart = "on-failure";
        };
      };
      services.arbor-networkd = {
        enable = true;
        package = networkManagerPackage;
        registrySnapshot = pkgs.writeText "accepted-network.json" (builtins.toJSON {
          format = "arbor-registry/accepted-state";
          version = 1;
          digest = "vm-lan";
          edges = [{
            source = "source";
            target = "target";
            network = "lan";
            provider = "lan";
            cost = 1;
            endpointGeneration = 1;
            capabilities = [ "ssh" ];
            transit = { ssh = true; };
          }];
          accepted = [{
            schema = "endpoint";
            recordId = "target-lan";
            generation = 1;
            payload = {
              id = "target-lan";
              node = "target";
              network = "lan";
              provider = "lan";
              address = "192.168.100.2";
              generation = 1;
              capabilities = [ "ssh" ];
              identityGeneration = 1;
              sshHostGeneration = 1;
              sshHostKey = "ssh-ed25519 AAAATEST";
            };
          }];
        });
        providerSockets.lan = "/run/arbor/lan.sock";
      };
    };
  };
  testScript = ''
    start_all()
    target.wait_for_unit("sshd.service")
    source.wait_for_unit("arbor-networkd.service")
    source.wait_for_unit("lan-provider.service")
    source.succeed("test -S /run/arbor/networkd.sock")
    source.succeed("echo '{\"version\":1,\"id\":\"vm\",\"operation\":\"route\",\"payload\":{\"source\":\"source\",\"target\":\"target\",\"capability\":\"ssh\"}}' | ${pkgs.socat}/bin/socat -T 5 - UNIX-CONNECT:/run/arbor/networkd.sock | ${pkgs.jq}/bin/jq -e '.ok and .result.reachable and (.result.nodes[-1] == \"target\")'")
    source.succeed("${pkgs.iputils}/bin/ping -c 1 192.168.100.2")
  '';
}
