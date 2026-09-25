import BraidedTrain

/-! Prints the axioms each main theorem depends on. `make proofs` fails if any output
line mentions `sorryAx` or `Classical.choice`. -/

open BraidedTrain

#print axioms landed_passes
#print axioms landed_eq_gated
#print axioms checkLanding_iff
#print axioms checkLanding_refuses_moved
#print axioms segments_land_last_gated
#print axioms prefix_is_fold
#print axioms admitted_iff
#print axioms read_failure_never_holds
#print axioms all_gated_iff_each_prefix
#print axioms retry_iff
#print axioms held_verdict_stands
#print axioms no_reopen_outside_reads
#print axioms strands_comm
#print axioms interleaved_landing
#print axioms two_owners_end_gated
#print axioms reland_tree
#print axioms reland_gate
#print axioms count_unionLines
#print axioms unionLines_assoc
#print axioms unionLines_comm
#print axioms union_order_visible
#print axioms change_comm
#print axioms family_perm
