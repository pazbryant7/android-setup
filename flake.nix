{
  description = "Full-stack dev environment (replaces Mason toolchain)";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312.withPackages (ps: [
          ps.mypy
          ps.pytest
          ps.pytest-cov
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            android-tools
            just
            python
            ruff
            typos
          ];

          shellHook = ''
            export PATH="${python}/bin:$PATH"
          '';
        };

        formatter = pkgs.nixfmt-tree;
      }
    );
}
