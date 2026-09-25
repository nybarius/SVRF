import BraidedTrain.Braid

/-!
# BraidedTrain.Interleaving — two trains landing path-disjoint families interleaved

With two owners landing path-disjoint families, does the commutation of disjoint strands
cover an interleaved landing on the base branch, each owner's gated end tree still being
the tree the base ends on, or is a joint end gate needed? Two answers, one per half.

The tree: `interleaved_landing`. Any interleaving of two strands with pairwise disjoint
written paths folds to the tree of either concatenation, so two owners never collide and
the base ends on one tree whatever the order of their merges. This extends `strands_comm`
from the two concatenations to every interleaving.

The gate: a gate is a function of the tree's content over the paths it reads (`restrict`).
`gate_transfers`: writes that miss those paths leave the verdict unchanged;
`gate_transfers_strand`: so does a whole strand of them. `two_owners_end_gated`: owner A's
verdict on its own end tree is its verdict on the interleaved end tree exactly when B's
written paths miss A's read paths. Without that hypothesis nothing carries A's verdict to
the joint tree: a gate that reads the whole tree (a whole-repository build) is reopened by
any write, and the joint end gate is then the only claim about the tree the base ends on.
So: declared read paths that miss the other owner's writes need no joint gate; a
whole-tree gate needs one owner with speculative stacking (`all_gated_iff_each_prefix`).
This is why SVRF runs as a single owner per repository.
-/

namespace BraidedTrain

/-- `Interleaving s₁ s₂ s`: `s` is `s₁` and `s₂` merged, each in its own order. -/
inductive Interleaving {α : Type} : List α → List α → List α → Prop
  | nil : Interleaving [] [] []
  | left {a : α} {as bs cs : List α} : Interleaving as bs cs → Interleaving (a :: as) bs (a :: cs)
  | right {b : α} {as bs cs : List α} : Interleaving as bs cs → Interleaving as (b :: bs) (b :: cs)

section
variable {Path Val : Type} [DecidableEq Path]

omit [DecidableEq Path] in
theorem disjoint_symm {a b : List (Path × Val)} (h : DisjointWrites a b) : DisjointWrites b a :=
  fun y hy x hx hyx => h x hx y hy hyx.symm

theorem foldl_interleaving (t : Path → Val) {s₁ s₂ s : List (List (Path × Val))}
    (hi : Interleaving s₁ s₂ s) :
    (∀ a ∈ s₁, ∀ b ∈ s₂, DisjointWrites a b) → s.foldl apply t = (s₁ ++ s₂).foldl apply t := by
  induction hi generalizing t with
  | nil => intro _; rfl
  | left _ ih =>
    intro hd
    simp only [List.foldl_cons, List.cons_append]
    exact ih (apply t _) (fun a ha b hb => hd a (List.mem_cons_of_mem _ ha) b hb)
  | @right b as bs cs _ ih =>
    intro hd
    simp only [List.foldl_cons]
    rw [ih (apply t b) (fun a ha b' hb' => hd a ha b' (List.mem_cons_of_mem _ hb'))]
    rw [List.foldl_append, List.foldl_append, List.foldl_cons]
    rw [foldl_apply_disjoint t b as (fun a ha => disjoint_symm (hd a ha b List.mem_cons_self))]

/-- Any interleaving of two disjoint strands lands the tree of their concatenation. -/
theorem interleaved_landing (t : Path → Val) {s₁ s₂ s : List (List (Path × Val))}
    (hi : Interleaving s₁ s₂ s) (hd : ∀ a ∈ s₁, ∀ b ∈ s₂, DisjointWrites a b) :
    fold unionStep t s = fold unionStep t (s₁ ++ s₂) := by
  rw [fold_union, fold_union, foldl_interleaving t hi hd]

/-- A gate reading only `reads` gives the same verdict before and after writes that miss `reads`. -/
theorem gate_transfers {V : Type} (gate : List (Path × Val) → V) (reads : List Path)
    (t : Path → Val) (b : List (Path × Val)) (h : ∀ x ∈ b, x.1 ∉ reads) :
    gate (restrict (apply t b) reads) = gate (restrict t reads) := by
  congr 1
  exact restrict_congr reads
    (fun p hp => apply_eq_of_not_written t b p (fun x hx hxp => h x hx (hxp ▸ hp)))

theorem gate_transfers_strand {V : Type} (gate : List (Path × Val) → V) (reads : List Path) :
    ∀ (t : Path → Val) (s : List (List (Path × Val))), (∀ b ∈ s, ∀ x ∈ b, x.1 ∉ reads) →
      gate (restrict (s.foldl apply t) reads) = gate (restrict t reads)
  | _, [], _ => rfl
  | t, b :: bs, h => by
    simp only [List.foldl_cons]
    rw [gate_transfers_strand gate reads (apply t b) bs
          (fun c hc => h c (List.mem_cons_of_mem _ hc))]
    exact gate_transfers gate reads t b (h b List.mem_cons_self)

/-- Owner A's verdict on its own end tree is its verdict on any interleaved end tree, when B's
written paths miss A's read set. -/
theorem two_owners_end_gated {V : Type} (gate : List (Path × Val) → V) (reads : List Path)
    (m : Path → Val) {fa fb s : List (List (Path × Val))} (hi : Interleaving fa fb s)
    (hd : ∀ a ∈ fa, ∀ b ∈ fb, DisjointWrites a b) (hr : ∀ b ∈ fb, ∀ x ∈ b, x.1 ∉ reads) :
    gate (restrict (s.foldl apply m) reads) = gate (restrict (fa.foldl apply m) reads) := by
  rw [foldl_interleaving m hi hd, List.foldl_append]
  exact gate_transfers_strand gate reads (fa.foldl apply m) fb hr

end

end BraidedTrain
