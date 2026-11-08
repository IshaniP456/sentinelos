forbid (
  principal,
  action == Sentinel::Action::"MovePackages",
  resource
)
when {
  context.destination == "HAZMAT" || context.restricted_destination
};
