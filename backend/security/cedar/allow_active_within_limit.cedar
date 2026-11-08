permit (
  principal,
  action == Sentinel::Action::"MovePackages",
  resource
)
when {
  principal.status == "ACTIVE" &&
  context.count >= 1 &&
  context.count <= 10 &&
  context.count <= principal.max_transfer
};
