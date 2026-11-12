# Checks of the simulated patient

Both checks are blind reads by an LLM reader: the verdicts were written before the reader saw which run or model
decision an item came from.

## Patient replies

602 patient turns of the control arm on 85 cases (MedQA-CS 25, AgentClinic 20, MedCaseReasoning 20, DDXPlus 20),
seed 1, Qwen3.8-27B as patient and doctor, each read against the case record. A clear error withholds or contradicts
a recorded answer to what was asked, invents a health fact, or names a diagnosis outside the arm; a minor error leaves
out a peripheral recorded fact, gives a neighbouring fact as the answer, flatly denies something the record does not
contain, or hedges about something it states.

Result: 23 errors in 602 turns (1 clear, 22 minor), 3.8%; no definite invented fact.

## Dispute decisions

150 doctor turns drawn at random from the reactive arms (own worry and the three sources): the controller's decision
on whether the doctor disputed or asked about the worry agreed with the blind read in 149 of 150.
