import Lake
open Lake DSL

package "autoFormalization" where

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.24.0" -- 你指定了 master 分支

require PhysLean from git "https://github.com/HEPLean/PhysLean" @ "master"

require «doc-gen4» from git "https://github.com/leanprover/doc-gen4" @ "v4.24.0"

lean_lib AutoFormalization {

}
