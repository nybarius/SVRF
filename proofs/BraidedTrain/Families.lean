/-!
# BraidedTrain.Families — every family the enumeration returns is maximal

`svrf.rules.families` enumerates the maximal pairwise-compatible sets of pull requests with
Bron–Kerbosch and pivoting: `extend(R, P, X)` reports `R` when `P` and `X` are both empty;
otherwise it picks a pivot `u` from `P ∪ X` and, for each `v` of `P` not compatible with
`u` (in sorted order, the list computed once), recurses on `(R ∪ {v}, P ∩ N(v), X ∩ N(v))`
and then moves `v` from `P` to `X`. `choose_families` keeps the first family of the sorted
list. `bk` below is that recursion; the pivot and the iteration order are left arbitrary
(any function), so the result covers the code's choices. Finite lists, no Mathlib.

1. `bk_maximal`: under a symmetric compatibility relation, every set `bk` reports from
   `R = [], P = nodes, X = []` is pairwise compatible, drawn from the nodes, and maximal:
   every node left out is incompatible with some member (`Maximal`).
2. `conflictCompat` is the relation `families` builds from the conflict edges (distinct and
   not joined by an edge); `conflictCompat_symm` shows it is symmetric.
   `chosen_family_maximal`: every family the enumeration reports, so in particular the one
   `choose_families` keeps, holds no conflicting pair, and every pull request left out has
   a conflict edge to a kept one — the `with` list `choose_families` reports for it is
   never empty.

Depth: `bk` takes a depth bound so that Lean sees it terminate; soundness holds at every
bound, and the code's recursion is the unbounded one, which terminates because `P` loses
`v` at each level. Not proved here: that the enumeration finds every maximal set, so that
the first of the size-sorted list is a maximum one (a largest compatible set) and not only
a maximal one.
-/

namespace BraidedTrain

section BronKerbosch
variable {V : Type} [DecidableEq V] (compat : V → V → Bool)

/-- Pairwise compatible. -/
def Clique (R : List V) : Prop :=
  ∀ a ∈ R, ∀ b ∈ R, a ≠ b → compat a b = true

/-- A compatible set drawn from `U` that no node of `U` outside it can join. -/
def Maximal (U R : List V) : Prop :=
  Clique compat R ∧ (∀ a ∈ R, a ∈ U) ∧ ∀ w ∈ U, w ∉ R → ∃ a ∈ R, compat a w = false

/-- The loop over the non-neighbours of the pivot, with the recursive call `f`. -/
def bkLoop (f : List V → List V → List V → List (List V)) (R : List V) :
    List V → List V → List V → List (List V)
  | _, _, [] => []
  | P, X, v :: vs =>
    f (v :: R) (P.filter (compat v)) (X.filter (compat v)) ++
      bkLoop f R (P.filter (fun x => x != v)) (v :: X) vs

/-- Bron–Kerbosch with a pivot and an iteration order, to a depth bound. -/
def bk (pivot : List V → List V → V) (order : List V → List V) :
    Nat → List V → List V → List V → List (List V)
  | 0, _, _, _ => []
  | n + 1, R, P, X =>
    if P.isEmpty && X.isEmpty then [R]
    else bkLoop compat (bk pivot order n) R P X (order (P.filter (fun v => !compat (pivot P X) v)))

/-- The recursion's invariant. -/
structure Inv (U R P X : List V) : Prop where
  clique : Clique compat R
  sub : ∀ a ∈ R, a ∈ U
  cand : ∀ p ∈ P, p ∈ U ∧ ∀ a ∈ R, compat a p = true
  cover : ∀ w ∈ U, w ∉ R → (∀ a ∈ R, compat a w = true) → w ∈ P ∨ w ∈ X

omit [DecidableEq V] in
theorem exists_false_of_all_false {R : List V} {w : V} :
    R.all (fun a => compat a w) = false → ∃ a ∈ R, compat a w = false := by
  induction R with
  | nil => intro h; cases h
  | cons a R ih =>
    intro h
    cases ha : compat a w with
    | false => exact ⟨a, List.mem_cons_self, ha⟩
    | true =>
      have h' : (compat a w && R.all (fun a => compat a w)) = false := h
      rw [ha] at h'
      obtain ⟨b, hb, hb'⟩ := ih h'
      exact ⟨b, List.mem_cons_of_mem _ hb, hb'⟩

omit [DecidableEq V] in
theorem all_true_of_forall {R : List V} {w : V} (h : ∀ a ∈ R, compat a w = true) :
    R.all (fun a => compat a w) = true := by
  induction R with
  | nil => rfl
  | cons a R ih =>
    show (compat a w && R.all (fun a => compat a w)) = true
    rw [h a List.mem_cons_self]
    exact ih (fun b hb => h b (List.mem_cons_of_mem _ hb))

omit [DecidableEq V] in
theorem maximal_of_inv {U R : List V} (h : Inv compat U R [] []) : Maximal compat U R := by
  refine ⟨h.clique, h.sub, ?_⟩
  intro w hw hwR
  cases hall : R.all (fun a => compat a w) with
  | false => exact exists_false_of_all_false compat hall
  | true =>
    have hforall : ∀ a ∈ R, compat a w = true := by
      intro a ha
      exact (List.all_eq_true.mp hall) a ha
    rcases h.cover w hw hwR hforall with hp | hx
    · cases hp
    · cases hx

variable (hsymm : ∀ a b, compat a b = compat b a)
include hsymm

omit [DecidableEq V] in
theorem inv_extend {U R P X : List V} (h : Inv compat U R P X) {v : V} (hvU : v ∈ U)
    (hv : ∀ a ∈ R, compat a v = true) :
    Inv compat U (v :: R) (P.filter (compat v)) (X.filter (compat v)) := by
  refine ⟨?_, ?_, ?_, ?_⟩
  · intro a ha b hb hab
    rcases List.mem_cons.mp ha with ea | ha
    · rcases List.mem_cons.mp hb with eb | hb
      · exact absurd (ea.trans eb.symm) hab
      · rw [ea, hsymm]; exact hv b hb
    · rcases List.mem_cons.mp hb with eb | hb
      · rw [eb]; exact hv a ha
      · exact h.clique a ha b hb hab
  · intro a ha
    rcases List.mem_cons.mp ha with rfl | ha
    · exact hvU
    · exact h.sub a ha
  · intro p hp
    have hp' := List.mem_filter.mp hp
    refine ⟨(h.cand p hp'.1).1, ?_⟩
    intro a ha
    rcases List.mem_cons.mp ha with rfl | ha
    · exact hp'.2
    · exact (h.cand p hp'.1).2 a ha
  · intro w hw hwR hall
    have hwR' : w ∉ R := fun hm => hwR (List.mem_cons_of_mem _ hm)
    have hvw : compat v w = true := hall v List.mem_cons_self
    rcases h.cover w hw hwR' (fun a ha => hall a (List.mem_cons_of_mem _ ha)) with hp | hx
    · exact Or.inl (List.mem_filter.mpr ⟨hp, hvw⟩)
    · exact Or.inr (List.mem_filter.mpr ⟨hx, hvw⟩)

omit hsymm in
theorem inv_skip {U R P X : List V} (h : Inv compat U R P X) (v : V) :
    Inv compat U R (P.filter (fun x => x != v)) (v :: X) := by
  refine ⟨h.clique, h.sub, ?_, ?_⟩
  · intro p hp
    exact h.cand p (List.mem_filter.mp hp).1
  · intro w hw hwR hall
    by_cases hwv : w = v
    · exact Or.inr (hwv ▸ List.mem_cons_self)
    · rcases h.cover w hw hwR hall with hp | hx
      · exact Or.inl (List.mem_filter.mpr ⟨hp, by simp [hwv]⟩)
      · exact Or.inr (List.mem_cons_of_mem _ hx)

theorem bkLoop_maximal (U : List V) (f : List V → List V → List V → List (List V))
    (hf : ∀ R P X, Inv compat U R P X → ∀ C ∈ f R P X, Maximal compat U C) (R : List V) :
    ∀ (vs P X : List V), Inv compat U R P X →
      (∀ v ∈ vs, v ∈ U ∧ ∀ a ∈ R, compat a v = true) →
      ∀ C ∈ bkLoop compat f R P X vs, Maximal compat U C
  | [], _, _, _, _, C, hC => by cases hC
  | v :: vs, P, X, h, hvs, C, hC => by
    rcases List.mem_append.mp hC with hC | hC
    · have hv := hvs v List.mem_cons_self
      exact hf _ _ _ (inv_extend compat hsymm h hv.1 hv.2) C hC
    · exact bkLoop_maximal U f hf R vs _ _ (inv_skip compat h v)
        (fun w hw => hvs w (List.mem_cons_of_mem _ hw)) C hC

/-- Every set the recursion reports from a state satisfying the invariant is maximal. -/
theorem bk_sound (U : List V) (pivot : List V → List V → V) (order : List V → List V)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) :
    ∀ (n : Nat) (R P X : List V), Inv compat U R P X → ∀ C ∈ bk compat pivot order n R P X,
      Maximal compat U C
  | 0, _, _, _, _, C, hC => by cases hC
  | n + 1, R, P, X, h, C, hC => by
    unfold bk at hC
    by_cases he : (P.isEmpty && X.isEmpty) = true
    · rw [if_pos he] at hC
      have hC' : C = R := List.mem_singleton.mp hC
      subst hC'
      have hP : P = [] := List.isEmpty_iff.mp (Bool.and_eq_true_iff.mp he).1
      have hX : X = [] := List.isEmpty_iff.mp (Bool.and_eq_true_iff.mp he).2
      subst hP; subst hX
      exact maximal_of_inv compat h
    · rw [if_neg he] at hC
      refine bkLoop_maximal compat hsymm U _ (bk_sound U pivot order horder n) R _ P X h ?_ C hC
      intro v hv
      exact h.cand v (List.mem_filter.mp (horder _ v hv)).1

/-- Every set Bron–Kerbosch reports from the start state (`R = []`, `P = nodes`, `X = []`)
is a maximal compatible set of the nodes. -/
theorem bk_maximal (U : List V) (pivot : List V → List V → V) (order : List V → List V)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) (n : Nat) :
    ∀ C ∈ bk compat pivot order n [] U [], Maximal compat U C := by
  refine bk_sound compat hsymm U pivot order horder n [] U [] ⟨?_, ?_, ?_, ?_⟩
  · intro a ha; cases ha
  · intro a ha; cases ha
  · intro p hp; exact ⟨hp, fun a ha => by cases ha⟩
  · intro w hw _ _; exact Or.inl hw

end BronKerbosch

/-! ## The relation `families` builds from conflict edges -/

section Conflicts
variable {V : Type} [DecidableEq V]

/-- Two pull requests conflict: an edge joins them, in either direction. -/
def conflicts (edges : List (V × V)) (a b : V) : Bool :=
  edges.contains (a, b) || edges.contains (b, a)

/-- Compatible: distinct and not in conflict (`compatible[n]` in `families`). -/
def conflictCompat (edges : List (V × V)) (a b : V) : Bool :=
  a != b && !conflicts edges a b

theorem conflictCompat_symm (edges : List (V × V)) (a b : V) :
    conflictCompat edges a b = conflictCompat edges b a := by
  unfold conflictCompat conflicts
  rw [bne_comm, Bool.or_comm (edges.contains (a, b))]

/-- The family `choose_families` keeps (any family the enumeration reports) holds no
conflicting pair, and every pull request left out conflicts with a kept one. -/
theorem chosen_family_maximal (edges : List (V × V)) (nodes : List V)
    (pivot : List V → List V → V) (order : List V → List V)
    (horder : ∀ l, ∀ v ∈ order l, v ∈ l) (n : Nat) (C : List V)
    (hC : C ∈ bk (conflictCompat edges) pivot order n [] nodes []) :
    (∀ a ∈ C, a ∈ nodes) ∧ (∀ a ∈ C, ∀ b ∈ C, a ≠ b → conflicts edges a b = false) ∧
      ∀ w ∈ nodes, w ∉ C → ∃ a ∈ C, conflicts edges a w = true := by
  obtain ⟨hcl, hsub, hmax⟩ :=
    bk_maximal (conflictCompat edges) (conflictCompat_symm edges) nodes pivot order horder n C hC
  refine ⟨hsub, ?_, ?_⟩
  · intro a ha b hb hab
    have := hcl a ha b hb hab
    unfold conflictCompat at this
    cases hc : conflicts edges a b
    · rfl
    · rw [hc] at this; simp at this
  · intro w hw hwC
    obtain ⟨a, ha, hf⟩ := hmax w hw hwC
    refine ⟨a, ha, ?_⟩
    have hne : a ≠ w := fun e => hwC (e ▸ ha)
    unfold conflictCompat at hf
    cases hc : conflicts edges a w
    · rw [hc] at hf; simp [hne] at hf
    · rfl

/-- Conflicts 1–2 and 2–3 among four pull requests: the enumeration reports exactly the two
maximal families, {1, 3, 4} and {2, 4}. -/
example : bk (conflictCompat [((1 : Nat), (2 : Nat)), (2, 3)]) (fun P X => (P ++ X).headD 0) id 4
    [] [1, 2, 3, 4] [] = [[4, 3, 1], [4, 2]] := by
  decide

end Conflicts

end BraidedTrain
