export interface Example {
  category: "Knowledge base" | "Web" | "Hybrid";
  question: string;
}

export const EXAMPLES: Example[] = [
  { category: "Knowledge base", question: "What is our API rate limit, and what happens when a key exceeds it?" },
  { category: "Knowledge base", question: "How should access be revoked when someone leaves the team?" },
  { category: "Hybrid", question: "How does our on-call rotation compare to typical SRE practice?" },
  { category: "Hybrid", question: "Summarize our incident severity levels and how they compare to industry-standard SRE practices." },
  { category: "Web", question: "What are the latest features released in LangGraph?" },
  { category: "Knowledge base", question: "When are deploy freeze windows, and how are database migrations handled?" },
];

export interface KnowledgeDoc {
  file: string;
  title: string;
  topics: string[];
}

/** Mirrors data/sample_docs — the corpus the RAG index is built from. */
export const KNOWLEDGE_BASE: KnowledgeDoc[] = [
  { file: "access_control.md", title: "Access Control", topics: ["Least privilege", "Authentication", "Offboarding", "Production data"] },
  { file: "api_policies.md", title: "API Policies", topics: ["Rate limiting", "Versioning", "Authentication"] },
  { file: "deployment.md", title: "Deployment Pipeline", topics: ["Standard path", "Freeze windows", "Migrations", "Feature flags"] },
  { file: "engineering_handbook.md", title: "Engineering Handbook", topics: ["Deploy process", "On-call", "Severity levels"] },
  { file: "incident_response.md", title: "Incident Response", topics: ["Severity levels", "Declaring", "Roles", "Postmortems"] },
  { file: "oncall_runbook.md", title: "On-call Runbook", topics: ["Rotation", "Handover", "Procedures", "What not to do"] },
  { file: "security_policy.md", title: "Security Policy", topics: ["Data retention", "Access control", "Vuln reporting"] },
  { file: "sre_practices.md", title: "SRE Practices", topics: ["SLOs", "Error budgets", "Toil", "Monitoring"] },
];
