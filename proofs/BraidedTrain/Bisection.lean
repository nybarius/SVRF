/-!
# BraidedTrain.Bisection — termination, gate count and outcome of `Train.settle_red`

`Train.settle_red` receives a family whose gate was red. A single pull request is held.
Otherwise the family is cut at `len // 2`; each half is gated; a green half lands, a red
half is settled again the same way. `settle` below is that procedure over a gate model
in which a set of pull requests is green exactly when it contains no bad pull request (a
monotone gate). Finite lists, no Mathlib.

1. Termination: `settle` is defined by well-founded recursion on the family's length; for a
   family of two or more, both halves are strictly shorter (`take_half_lt`,
   `drop_half_lt`), so Lean accepts it only because it terminates.
2. `settle_outcome`: on a red family (one with a bad pull request) bisection holds exactly
   the bad pull requests and lands exactly the rest, each in the family's order.
3. `settle_gates_le`: bisecting a family of at most `2^k` pull requests with `r` bad ones
   costs at most `2·r·k` gates, so the family's own gate plus bisection is at most
   `2·r·⌈log₂ n⌉ + 1` (`bisection_gates_le`, with `clog2 n` the least `k` with
   `n ≤ 2^k`, `le_two_pow_clog2`). The code gates both halves even when the first half
   comes back green (the second is then certainly red under a monotone gate); the bound
   counts those gates too.

Modelling boundary: the halves are replanned on the current base, so in the code a pull
request can also drop out of a half by conflicting with what the first half landed, and a
gate that could not run is retried rather than counted; both only remove gates from the
count. The monotone gate (a set is green iff no member is bad) is a hypothesis about the
gate command, not something the train checks.
-/

namespace BraidedTrain

/-- The outcome of settling a red family: held and landed pull requests, gates spent. -/
structure Settled (α : Type) where
  held : List α
  landed : List α
  gates : Nat

variable {α : Type} (bad : α → Bool)

/-- A set is green under the monotone gate: no member is bad. -/
def clean (xs : List α) : Bool :=
  xs.all (fun x => !bad x)

theorem take_half_lt (xs : List α) (h : ¬ xs.length ≤ 1) :
    (xs.take (xs.length / 2)).length < xs.length := by
  rw [List.length_take]
  have : xs.length / 2 < xs.length := Nat.div_lt_self (by omega) (by decide)
  exact Nat.lt_of_le_of_lt (Nat.min_le_left _ _) this

theorem drop_half_lt (xs : List α) (h : ¬ xs.length ≤ 1) :
    (xs.drop (xs.length / 2)).length < xs.length := by
  rw [List.length_drop]
  have : 0 < xs.length / 2 := Nat.div_pos (by omega) (by decide)
  omega

/-- One half after the red parent: gated once; landed if green, settled again if red. -/
def visit (part : List α) (settled : Settled α) : Settled α :=
  if clean bad part then ⟨[], part, 1⟩ else ⟨settled.held, settled.landed, settled.gates + 1⟩

/-- `Train.settle_red` over the monotone gate. -/
def settle (xs : List α) : Settled α :=
  if _hlen : xs.length ≤ 1 then ⟨xs, [], 0⟩ else
    let a := visit bad (xs.take (xs.length / 2)) (settle (xs.take (xs.length / 2)))
    let b := visit bad (xs.drop (xs.length / 2)) (settle (xs.drop (xs.length / 2)))
    ⟨a.held ++ b.held, a.landed ++ b.landed, a.gates + b.gates⟩
termination_by xs.length
decreasing_by
  · exact take_half_lt xs _hlen
  · exact drop_half_lt xs _hlen

/-- A red part: some member is bad. -/
def Red (xs : List α) : Prop := ∃ x ∈ xs, bad x = true

theorem red_of_not_clean : ∀ {xs : List α}, clean bad xs = false → Red bad xs
  | [], h => by cases h
  | x :: xs, h => by
    cases hb : bad x with
    | true => exact ⟨x, List.mem_cons_self, hb⟩
    | false =>
      have hrest : clean bad xs = false := by
        have h' : (!bad x && clean bad xs) = false := h
        rw [hb] at h'
        exact h'
      obtain ⟨y, hy, hby⟩ := red_of_not_clean hrest
      exact ⟨y, List.mem_cons_of_mem _ hy, hby⟩

theorem filter_bad_of_clean : ∀ {xs : List α}, clean bad xs = true →
    xs.filter bad = [] ∧ xs.filter (fun x => !bad x) = xs
  | [], _ => ⟨rfl, rfl⟩
  | x :: xs, h => by
    cases hb : bad x with
    | true => simp [clean, List.all_cons, hb] at h
    | false =>
      have hrest : clean bad xs = true := by
        simpa [clean, List.all_cons, hb] using h
      obtain ⟨e1, e2⟩ := filter_bad_of_clean hrest
      simp only [List.filter_cons, hb, e1, e2]
      exact ⟨rfl, rfl⟩

theorem settle_eq (xs : List α) (h : ¬ xs.length ≤ 1) :
    settle bad xs =
      ⟨(visit bad (xs.take (xs.length / 2)) (settle bad (xs.take (xs.length / 2)))).held ++
        (visit bad (xs.drop (xs.length / 2)) (settle bad (xs.drop (xs.length / 2)))).held,
       (visit bad (xs.take (xs.length / 2)) (settle bad (xs.take (xs.length / 2)))).landed ++
        (visit bad (xs.drop (xs.length / 2)) (settle bad (xs.drop (xs.length / 2)))).landed,
       (visit bad (xs.take (xs.length / 2)) (settle bad (xs.take (xs.length / 2)))).gates +
        (visit bad (xs.drop (xs.length / 2)) (settle bad (xs.drop (xs.length / 2)))).gates⟩ := by
  rw [settle, dif_neg h]

/-- Bisection of a red family holds exactly its bad pull requests and lands the rest. -/
theorem settle_outcome (xs : List α) (hred : Red bad xs) :
    (settle bad xs).held = xs.filter bad ∧
      (settle bad xs).landed = xs.filter (fun x => !bad x) := by
  by_cases h : xs.length ≤ 1
  · rw [settle, dif_pos h]
    obtain ⟨x, hx, hb⟩ := hred
    match xs, h, hx with
    | [y], _, hx =>
      have hy : x = y := List.mem_singleton.mp hx
      subst hy
      simp [hb]
  · rw [settle_eq bad xs h]
    have part : ∀ ys : List α, ys.length < xs.length →
        (visit bad ys (settle bad ys)).held = ys.filter bad ∧
          (visit bad ys (settle bad ys)).landed = ys.filter (fun x => !bad x) := by
      intro ys _
      unfold visit
      cases hc : clean bad ys with
      | true =>
        simp only [if_true]
        exact ⟨(filter_bad_of_clean bad hc).1.symm, (filter_bad_of_clean bad hc).2.symm⟩
      | false =>
        simp only [Bool.false_eq_true, if_false]
        exact settle_outcome ys (red_of_not_clean bad hc)
    obtain ⟨h1, l1⟩ := part _ (take_half_lt xs h)
    obtain ⟨h2, l2⟩ := part _ (drop_half_lt xs h)
    simp only [h1, h2, l1, l2, ← List.filter_append, List.take_append_drop]
    exact ⟨trivial, trivial⟩
termination_by xs.length
decreasing_by
  all_goals assumption

theorem length_filter_append (p : α → Bool) (a b : List α) :
    ((a ++ b).filter p).length = (a.filter p).length + (b.filter p).length := by
  rw [List.filter_append, List.length_append]

theorem red_filter_pos {xs : List α} (h : Red bad xs) : 1 ≤ (xs.filter bad).length := by
  obtain ⟨x, hx, hb⟩ := h
  exact List.length_pos_iff_exists_mem.mpr ⟨x, List.mem_filter.mpr ⟨hx, hb⟩⟩

/-- Bisecting a red family of at most `2^k` pull requests, `r` of them bad, costs at most
`2·r·k` gates. -/
theorem settle_gates_le : ∀ (k : Nat) (xs : List α), xs.length ≤ 2 ^ k → Red bad xs →
    (settle bad xs).gates ≤ 2 * (xs.filter bad).length * k
  | k, xs, hk, hred => by
    by_cases h : xs.length ≤ 1
    · rw [settle, dif_pos h]; exact Nat.zero_le _
    · cases k with
      | zero => exact absurd hk (by simp; omega)
      | succ k =>
        rw [settle_eq bad xs h]
        have hpow : 2 ^ (k + 1) = 2 * 2 ^ k := by rw [Nat.pow_succ, Nat.mul_comm]
        have part : ∀ ys : List α, ys.length ≤ 2 ^ k →
            (visit bad ys (settle bad ys)).gates ≤ 1 + 2 * (ys.filter bad).length * k := by
          intro ys hys
          unfold visit
          cases hc : clean bad ys with
          | true =>
            simp only [if_true]
            exact Nat.le_add_right 1 _
          | false =>
            simp only [Bool.false_eq_true, if_false]
            have := settle_gates_le k ys hys (red_of_not_clean bad hc)
            omega
        have hL : (xs.take (xs.length / 2)).length ≤ 2 ^ k := by
          rw [List.length_take]
          have : xs.length / 2 ≤ 2 ^ k := by omega
          exact Nat.le_trans (Nat.min_le_left _ _) this
        have hR : (xs.drop (xs.length / 2)).length ≤ 2 ^ k := by
          rw [List.length_drop]
          omega
        have gL := part _ hL
        have gR := part _ hR
        have hr := red_filter_pos bad hred
        have split : (xs.filter bad).length =
            ((xs.take (xs.length / 2)).filter bad).length +
              ((xs.drop (xs.length / 2)).filter bad).length := by
          rw [← length_filter_append, List.take_append_drop]
        show _ + _ ≤ _
        generalize ((xs.take (xs.length / 2)).filter bad).length = a at gL split
        generalize ((xs.drop (xs.length / 2)).filter bad).length = b at gR split
        rw [split] at hr ⊢
        have e1 : 2 * (a + b) * (k + 1) = 2 * a * k + 2 * b * k + 2 * (a + b) := by
          rw [Nat.mul_add, Nat.mul_one, Nat.mul_add 2 a b, Nat.add_mul]
        rw [e1]
        omega

/-- `⌈log₂ n⌉`: the least `k` with `n ≤ 2^k`. -/
def clog2 (n : Nat) : Nat :=
  if h : n ≤ 1 then 0 else clog2 ((n + 1) / 2) + 1
termination_by n
decreasing_by omega

theorem le_two_pow_clog2 (n : Nat) : n ≤ 2 ^ clog2 n := by
  by_cases h : n ≤ 1
  · rw [clog2, dif_pos h]; simpa using h
  · rw [clog2, dif_neg h, Nat.pow_succ]
    have := le_two_pow_clog2 ((n + 1) / 2)
    omega
termination_by n
decreasing_by omega

/-- The family's own red gate plus its bisection: at most `2·r·⌈log₂ n⌉ + 1` gates. -/
theorem bisection_gates_le (xs : List α) (hred : Red bad xs) :
    1 + (settle bad xs).gates ≤ 2 * (xs.filter bad).length * clog2 xs.length + 1 := by
  have := settle_gates_le bad (clog2 xs.length) xs (le_two_pow_clog2 xs.length) hred
  omega

end BraidedTrain
