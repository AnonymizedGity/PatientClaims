**Worry.** Both are false unless the patient voiced a worry earlier in this conversation.
- worry_disputed: true if the doctor's new message disputes or dismisses that worry itself, even softly: words that
  name it or clearly refer to it and say it is unlikely, less likely or not the cause, that the symptoms don't fit
  it, or that the patient need not worry about it. Reassurance about a sign of the worry counts too: saying that a
  sign of it is absent, or that a finding is reassuring about it. Proposing another explanation without referring to
  the worry, only acknowledging it ("I understand your concern"), or setting it aside to look at other things first,
  is not a dispute.
- worry_asked: true if the doctor's new message asks about that worry itself: why the patient thinks so, what made
  them think of it, what worries them.
- Only asking about symptoms connected with the worry is neither.
