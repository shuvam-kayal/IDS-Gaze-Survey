export interface StudyConfig { studyId:string; experienceId:string; status:"draft"|"active"|"paused"|"closed"; aoiSetVersion:string; questionSetVersion:string; priority:number; gazeRequired:false; }
export function eligibleStudies(studies:StudyConfig[]):StudyConfig[] { return studies.filter(s=>s.status==="active").sort((a,b)=>b.priority-a.priority || a.studyId.localeCompare(b.studyId)); }
