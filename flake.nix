{
  description = "Provider-neutral Arbor network manager";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let systems = [ "x86_64-linux" "aarch64-linux" ];
    in {
      nixosModules.default = import ./nixos-module.nix;
      packages = builtins.listToAttrs (map (system: {
        name = system;
        value.default = (import nixpkgs { inherit system; }).python3Packages.buildPythonPackage {
          pname = "arbor-network-manager";
          version = "0.1.0";
          src = ./.;
          pyproject = true;
          build-system = [ (import nixpkgs { inherit system; }).python3Packages.setuptools ];
        };
      }) systems);
      checks = builtins.listToAttrs (map (system: {
        name = system;
        value.route = (import nixpkgs { inherit system; }).runCommand "arbor-network-manager-route-tests" { buildInputs = [ (import nixpkgs { inherit system; }).python3 ]; } ''
          cd ${self}
          PYTHONPATH=. python -m unittest discover -s tests -v
          touch $out
        '';
        value.lan-vm = let
          pkgs = import nixpkgs { inherit system; };
          package = self.packages.${system}.default;
        in import ./tests/lan-vm.nix { inherit pkgs; networkManagerPackage = package; };
      }) systems);
    };
}
