function setTrajectoryOutcome(_outcome) {}
function setGraphRunningStep(_stepId) {}
function clearGraphRunningStep(_stepId) {}
function resetGraph() {}
function resizeGraph() {}
function updateGraph(_payload) {}
function recordActionExecution(_event) {}
function selectGraphActionForStep(_stepId) { return false; }
function clearGraphSelection() {}
function isNoopDetectionEligibleAction(_actionNode) { return false; }

window.setTrajectoryOutcome = setTrajectoryOutcome;
window.setGraphRunningStep = setGraphRunningStep;
window.clearGraphRunningStep = clearGraphRunningStep;
window.resetGraph = resetGraph;
window.resizeGraph = resizeGraph;
window.updateGraph = updateGraph;
window.recordActionExecution = recordActionExecution;
window.selectGraphActionForStep = selectGraphActionForStep;
window.clearGraphSelection = clearGraphSelection;
window.isNoopDetectionEligibleAction = isNoopDetectionEligibleAction;
window.actionNodeForStep = () => null;
