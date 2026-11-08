forbid (
  principal,
  action == Sentinel::Action::"MovePackages",
  resource
)
unless {
  principal.status == "ACTIVE"
};
