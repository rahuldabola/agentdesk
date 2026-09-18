import { Brain, CheckCheck, PenLine, Search, Workflow, type LucideIcon } from "lucide-react";
import type { AgentKey } from "./agents";

export const AGENT_ICONS: Record<AgentKey, LucideIcon> = {
  planner: Workflow,
  researcher: Search,
  analyst: Brain,
  writer: PenLine,
  critic: CheckCheck,
};
