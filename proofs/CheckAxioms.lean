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
#print axioms stack_lands_gated
#print axioms stack_fold_through
#print axioms stacked_verdict_does_not_carry
#print axioms stackStatus_landed_iff
#print axioms stackStatus_void_iff
#print axioms stackStatus_bisected_iff
#print axioms settle_outcome
#print axioms settle_gates_le
#print axioms le_two_pow_clog2
#print axioms bisection_gates_le
#print axioms bk_maximal
#print axioms conflictCompat_symm
#print axioms chosen_family_maximal
#print axioms retarget_headTree
#print axioms retarget_fold
#print axioms retarget_lands_same
#print axioms retarget_after_parent
#print axioms bk_complete
#print axioms codePivot_mem
#print axioms grow_maximal
#print axioms chosen_family_maximum
