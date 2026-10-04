import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { Activity, ChannelName, Identity, SessionState } from "./types";

export type Language = "en" | "ar";

const en = {
  dir: "ltr" as "ltr" | "rtl",
  app: {
    skip: "Skip to content",
    footer: "Experimental engineering preview · not a clinical or diagnostic tool.",
    leaveTitle: "End this session and go back?",
    leaveBody:
    "The session is still in progress. Leaving ends it now; its live view and event log will not be kept. Nothing is recorded.",
    leaveConfirm: "End session and leave",
    keepSession: "Keep session",
  },
  topbar: {
    title: "ABA Visual Assistant",
    subtitle: "Session assistant · engineering preview",
    back: "Back to all sessions",
    replay: "RECORDED SESSION",
    simulation: "SIMULATION",
    replayHint: "Earlier analysis replayed against the matching video. Not live inference; nothing is recorded.",
    simulationHint: "Synthetic source and observations. No camera, no model inference, nothing is recorded.",
    switchTo: "العربية",
    switchLabel: "Switch the interface to Arabic",
    connection: {
      idle: "No session",
      connecting: "Connecting",
      live: "Stream connected",
      reconnecting: "Reconnecting",
      closed: "Stream closed",
    },
  },
  launcher: {
    badge: "Local only · nothing leaves this machine",
    heading: "Clear evidence, in the moment.",
    intro:
    "A calm view for the therapist during or after a session: who is being observed, what changed and when, and which moments deserve a look. You interpret the evidence and make every decision.",
    principles: [
      { title: "Therapist selects the child", body: "No face recognition. Identity never switches automatically." },
      { title: "Unobservable ≠ absent", body: "When the child is hidden or uncertain, nothing is reported." },
      { title: "Signs, not conclusions", body: "Observable signs for your review. No diagnosis, no scores." },
    ],
    chooseTitle: "Recorded sessions",
    chooseBody: "Each session plays its own video with the observation channels measured for it.",
    empty: "No recorded sessions yet. Start the app with --library pointing at a folder of sessions (one sub-folder with session.json each).",
    recordedPill: "Recorded session",
    recordedSummary: (channels: string) => `Video with ${channels}.`,
    simulationPill: "Engineering test",
    open: "Open session",
    serverDown: "Cannot reach the local live-session server. Start it with python -m aba_demo.live.",
    precomputed: "Precomputed replay",
    launch: "Launch",
    launchAria: (title: string) => `Launch ${title}`,
  },
  controls: {
    progress: "Session progress",
    steps: ["Open source", "Select target", "Observe", "Review"],
    open: "Open source",
    lock: "Lock target",
    confirmChild: "Confirm child",
    start: "Start session",
    pause: "Pause",
    resume: "Resume",
    end: "End session",
    confirmEnd: "Confirm end session",
    again: "Run again",
    newSession: "New session",
  },
  workspace: {
    allScenarios: "All scenarios",
    session: "Session",
    breadcrumb: "Breadcrumb",
    details: "Session details",
    streamDown: "Event stream interrupted — showing the last known state as stale while reconnecting.",
    lost: "This session is no longer available on the server (it may have restarted). Nothing shown here is current.",
    newSession: "New session",
    late: (age: string) => `Analysis is running ${age} s behind live. Results are marked late and not shown as current.`,
    gap: "Some events were not retained during reconnection; the log may be incomplete.",
    dismiss: "Dismiss",
    failed: "Session failed",
    ended: "Session ended",
    noVideo: "No video was recorded.",
    ledger: (frames: number, dropped: number, sha: string) =>
      `Frame ledger verified: ${frames} frames, ${dropped} dropped · sha256 ${sha}…`,
    noLedger: "No complete frame ledger was produced.",
    stats: { videoTime: "Video time", observations: "Observations", flags: "Flags", gaps: "Analysis gaps", late: "Late results" },
  },
  stage: {
    aria: "Synthetic scene visualization",
    synthetic: "SYNTHETIC SOURCE · NO VIDEO",
    replay: "RECORDED SESSION · EARLIER ANALYSIS REPLAYED",
    video: "Recorded session video",
    ended: "SESSION ENDED · LAST KNOWN STATE",
    stale: "STALE · LAST KNOWN STATE",
    uncertain: "Identity uncertain",
    confirmed: "Target confirmed",
    locked: "Target locked",
    videoTime: "Video time",
    observations: "observations",
    analysis: "analysis",
    resultAge: "result age",
    late: (seconds: string) => `LATE · ${seconds} s behind`,
    overlayUncertain: "Target not visible — observations suppressed until identity is confirmed",
    notOpened: "Source not opened",
    select: "Click the child you will observe to lock the target",
    confirmRecorded: "The child was selected when this recording was analysed (green box). Confirm to continue.",
    paused: "Paused — session clock and analysis halted",
    task: "TASK AREA",
    seat: "SEAT",
    target: "TARGET",
  },
  home: {
    badge: "Local analysis · context notes use an external model",
    heading: "Clear evidence from every session.",
    intro:
    "Choose a session video and click the child. The assistant marks what changed and when: posture, large movement, facing the task, and context notes. You interpret the evidence and make every decision.",
    newTitle: "Analyse a new video",
    newBody:
    "MP4, MOV or WebM from this computer. The video stays on this machine; only a few frames around detected moments are sent for context notes.",
    choose: "Choose a video",
    drop: "or drop it here",
    uploading: (percent: number) => `Copying the video… ${percent}%`,
    resume: "Continue the current analysis",
    libraryTitle: "Analysed sessions",
    libraryBody: "Open a session to review its video with the moments the channels found.",
    libraryEmpty: "No analysed sessions yet. Analyse a video to start.",
    open: "Review",
    moments: (count: number) => `${count} moments`,
    flags: (count: number) => `${count} for review`,
    noMoments: "No moment detected",
    engineeringTitle: "Engineering tests",
    engineeringBody: "Synthetic scenarios that exercise the live-session shell. Not recordings.",
    serverDown: "Cannot reach the local server. Start it with run_live.bat.",
  },
  analysis: {
    title: "New analysis",
    preparing: "Opening the video and loading the model…",
    selectTitle: "Click the child you will observe",
    selectBody: "Every person found on the first frame has a box. Click inside the child's box.",
    reselectTitle: "The child was lost — click the child again",
    reselectBody: (time: string) =>
      `Tracking paused at ${time}. Click the child to continue, or skip ahead while the child is out of view.`,
    chosen: "Child selected",
    notChosen: "No child selected yet",
    sessionTitle: "Session title",
    activity: "Activity in this video",
    activityHint: "Decides which moments are marked for review, e.g. standing up during table work.",
    taskArea: "Task area (optional)",
    taskHint: "Draw the area where the task happens, e.g. the table, to measure facing the task.",
    draw: "Draw task area",
    drawing: "Drag on the frame…",
    clear: "Clear",
    contextNote:
    "Context notes: a few frames around each detected moment are sent to DeepSeek through OpenRouter (data collection denied) for a short suggestion.",
    start: "Start analysis",
    confirm: "Continue with this child",
    skip: "Child not visible — skip 2 s",
    continueWithout: "Continue without asking again",
    running: "Analysing the video",
    runningHint: "You can leave this page; the analysis keeps running on this computer.",
    stages: {
      tracking: "Following the child",
      posture: "Posture",
      movement: "Large movement",
      orientation: "Facing the task",
      context: "Context notes",
    } as Record<string, string>,
    status: { pending: "Waiting", running: "Running", done: "Done", skipped: "Skipped", failed: "Failed" } as Record<string, string>,
    notes: {
      no_task_region: "No task area drawn",
      provider_not_configured: "No model key configured",
      invalid_config: "Model key file is invalid",
      no_moments: "No moments to describe",
      no_local_channel: "No local channel",
    } as Record<string, string>,
    done: "Analysis complete",
    openReview: "Open review",
    failed: "The analysis stopped",
    cancelled: "Analysis cancelled",
    cancel: "Cancel analysis",
    back: "Back to sessions",
    reselections: (count: number, max: number) => `Reselections: ${count} of ${max}`,
    childConfirmed: (percent: number) => `Child confirmed in ${percent}% of the video`,
    errors: {
      child_not_confirmed_enough:
      "The child could not be followed for enough of the video (out of view or not reselected). Try again and click the child when asked.",
      no_channel_produced: "No observation channel could be measured on this video.",
      unsupported_video_type: "Unsupported file. Choose an MP4, MOV or WebM video.",
      video_too_large: "The video is larger than 8 GB.",
      empty_upload: "The file is empty.",
      video_unreadable: "This video could not be opened. Choose an MP4 recorded by a camera or phone.",
      analysis_in_progress: "Another analysis is running. Finish or cancel it first.",
      click_ambiguous: "That point is inside more than one person. Click a part of the child no one else covers.",
      click_not_on_person: "Click inside the child's box.",
      server_down: "Cannot reach the local server.",
    } as Record<string, string>,
    errorCode: (code: string) => `Technical code: ${code}`,
  },
  review: {
    back: "All sessions",
    analysed: (date: string) => `Analysed ${date}`,
    duration: "Duration",
    activity: "Activity",
    childConfirmed: "Child confirmed",
    timeline: "Session timeline",
    timelineHint: "Bands show the measured state; marks show detected moments. Click anywhere to jump.",
    channelsTitle: "What each channel saw",
    measured: (percent: number) => `Measured in ${percent}% of the video`,
    contextRead: (read: number, total: number) => `${read} of ${total} moments described`,
    events: (count: number) => (count === 0 ? "No event" : count === 1 ? "1 event" : `${count} events`),
    noEventObserved: "Observed — no change detected",
    now: "Now",
    notMeasuredNow: "not measured at this moment",
    notAnalysed: "Not analysed",
    reasons: {
      no_task_region: "no task area was drawn",
      provider_not_configured: "no model key configured",
      invalid_config: "the model key file is invalid",
      no_moments: "there were no moments to describe",
      no_local_channel: "no local channel",
    } as Record<string, string>,
    notInSession: "not run for this session",
    states: { sitting: "Sitting", standing: "Standing", toward: "Facing the task", away: "Turned away" } as Record<string, string>,
    momentsTitle: "Moments",
    loadError: "This session could not be loaded.",
  },
  card: {
    title: "For your review",
    during: (channel: string, activity: string) => `${channel} · during ${activity}`,
    from: "From",
    to: "To",
    note: "A visible change flagged by the provisional rules for this activity. It is a prompt for your review, not a conclusion about attention, intent, or behavior function.",
    acknowledge: "Acknowledge",
    unavailable: "Unavailable while the stream, identity or analysis is not current.",
    nothing: "Nothing needs your attention right now.",
  },
  facts: {
    title: "Session",
    scenario: "Scenario",
    identity: "Identity",
    notSelected: "Not selected",
    confirmed: "Confirmed",
    uncertain: "Uncertain",
    observations: "Observations",
    precomputed: "Precomputed (not live)",
    synthetic: "Synthetic",
    recorder: "Recorder",
    ledger: (frames: number) => `Ledger · ${frames} frames`,
    dropped: (frames: number) => ` · ${frames} dropped`,
    ledgerHint: "Simulated frame ledger: counts frames that reached the recorder. No pixels are stored.",
    flags: "Flags for review",
    gaps: "Analysis gaps",
    p95: "Analysis p95",
    late: "Late results",
  },
  activityCard: {
    title: "Activity context",
    hint: "Set by you. It decides which moments are flagged for review, e.g. standing up during table work.",
  },
  log: { title: "Event log", empty: "Events will appear here." },
  channels: {
    title: "Observation channels",
    note: "Observable signs only · provisional rules · not clinical labels",
    notLoaded: "Not loaded for this session",
    noEvent: "No event yet",
    soFar: (count: number) => `${count} so far`,
    aria: (channel: string, count: number | null) => `${channel}: ${count === null ? "not loaded" : `${count} events`}`,
  },
  strip: {
    title: "Session strip",
    empty: "Confirmed moments will appear here as the session reaches them.",
    emptyReview: "No moment was detected in this session. The lanes above show what each channel measured.",
    suggestion: "Model suggestion",
    watch: "Watch",
    watchAria: (time: string) => `Watch the moment at ${time}`,
    before: "Before",
    after: "After",
    modelSees: "Model sees the child",
    experimental: "experimental",
    agrees: "agrees with the measurement",
    disagrees: "needs checking: the model sees it differently",
    checkBadge: "Needs checking",
  },
  channel: {
    posture: "Posture",
    movement: "Large movement",
    orientation: "Facing the task",
    context: "Context",
  } as Record<ChannelName, string>,
  basis: {
    posture: "Sit ↔ stand from the child's own leg joints",
    movement: "Body centre moved more than one torso length",
    orientation: "Head turned away from the drawn task area",
    context: "Model note on marked moments · suggestion only",
  } as Record<ChannelName, string>,
  kind: {
    sit_to_stand: "Stood up",
    stand_to_sit: "Sat down",
    large_movement: "Large movement",
    turned_away_from_task: "Turned away from task",
    turned_back_to_task: "Turned back to task",
    context_note: "Context note",
  } as Record<string, string>,
  level: { flag: "For review", info: "Info" },
  origin: { measured: "Local measurement", suggested: "Model suggestion" },
  activity: { table: "Table work", movement: "Movement", break: "Break" } as Record<Activity, string>,
  sessionState: {
    created: "Created",
    previewing: "Preview",
    target_selected: "Target selected",
    running: "Running",
    paused: "Paused",
    stopping: "Stopping",
    completed: "Completed",
    failed: "Failed",
  } as Record<SessionState, string>,
  termination: {
    user_stop: "Stopped by therapist",
    source_eof: "Source reached its end",
    source_disconnected: "Source disconnected",
    worker_failed: "Analysis worker failed",
    server_shutdown: "Server shut down",
    user_left: "Left by therapist",
    recorder_failed: "Recorder failed",
  } as Record<string, string>,
  error: {
    provider_failed: "Analysis unavailable for a frame",
    source_disconnected: "Video source disconnected",
    worker_failed: "Analysis worker failed",
    recorder_failed: "Recorder failed — no complete recording",
  } as Record<string, string>,
  detail: {
    child_location: { at_table: "at the table", away_from_table: "away from the table", walking: "moving around", on_floor: "on the floor" } as Record<string, string>,
    child_handling_material: { yes: "holding material", no: "not holding material" } as Record<string, string>,
    notSeparable: "child not separable from adult",
    child_position_after: {
      seated: "seated", standing: "standing", walking: "walking", on_floor: "on the floor", held_by_adult: "held by an adult",
    } as Record<string, string>,
    adult_movement: {
      moved_closer: "the adult moved closer", moved_away: "the adult moved away", stayed: "the adult stayed in place",
      no_adult_visible: "no adult in view",
    } as Record<string, string>,
    materials_change: { added: "materials added", removed: "materials removed" } as Record<string, string>,
  },
  timeline: {
    identityConfirmed: "Identity confirmed",
    identityUncertain: "Identity uncertain",
    suppressed: "Observations suppressed",
    flag: (kind: string) => `${kind} — for review`,
    flagDetail: "Flag from the provisional rules",
    activity: (activity: string) => `Activity: ${activity}`,
    activityDetail: "Applies from this moment",
    errorDetail: "No observation was generated",
  },
};

export type Strings = typeof en;

const ar: Strings = {
  dir: "rtl",
  app: {
    skip: "تخطَّ إلى المحتوى",
    footer: "معاينة هندسية تجريبية · ليست أداة سريرية أو تشخيصية.",
    leaveTitle: "إنهاء هذه الجلسة والعودة؟",
    leaveBody: "الجلسة ما زالت جارية. المغادرة تنهيها الآن، ولن يُحفظ عرضها ولا سجل أحداثها. لا يُسجَّل أي شيء.",
    leaveConfirm: "إنهاء الجلسة والمغادرة",
    keepSession: "متابعة الجلسة",
  },
  topbar: {
    title: "المساعد المرئي ABA",
    subtitle: "مساعد الجلسات · معاينة هندسية",
    back: "العودة إلى كل الجلسات",
    replay: "جلسة مسجّلة",
    simulation: "محاكاة",
    replayHint: "تحليل سابق يُعاد تشغيله على الفيديو المطابق. ليس تحليلاً حياً، ولا يُسجَّل شيء.",
    simulationHint: "مصدر وملاحظات مصطنعة. لا كاميرا ولا نموذج ولا تسجيل.",
    switchTo: "English",
    switchLabel: "Switch the interface to English",
    connection: {
      idle: "لا توجد جلسة",
      connecting: "جارٍ الاتصال",
      live: "البث متصل",
      reconnecting: "جارٍ إعادة الاتصال",
      closed: "البث مغلق",
    },
  },
  launcher: {
    badge: "محلي فقط · لا يغادر شيء هذا الجهاز",
    heading: "أدلة واضحة، في لحظتها.",
    intro:
    "عرض هادئ للمعالج أثناء الجلسة أو بعدها: من الطفل الذي تتم ملاحظته، وما الذي تغيّر ومتى، وأي اللحظات تستحق المراجعة. أنت من يفسّر الأدلة ويتخذ كل قرار.",
    principles: [
      { title: "المعالج يحدد الطفل", body: "لا تعرّف على الوجوه، ولا تتغير الهوية تلقائياً أبداً." },
      { title: "غير المرصود ≠ غير الموجود", body: "عندما يختفي الطفل أو تكون هويته غير مؤكدة، لا يُسجَّل شيء." },
      { title: "علامات لا استنتاجات", body: "علامات مرئية لمراجعتك. لا تشخيص ولا درجات." },
    ],
    chooseTitle: "الجلسات المسجّلة",
    chooseBody: "كل جلسة تعرض فيديوها مع قنوات الملاحظة التي قيست لها.",
    empty: "لا توجد جلسات مسجّلة بعد. شغّل التطبيق مع الخيار --library ووجّهه إلى مجلد الجلسات (مجلد فرعي لكل جلسة فيه session.json).",
    recordedPill: "جلسة مسجّلة",
    recordedSummary: (channels: string) => `فيديو مع ${channels}.`,
    simulationPill: "اختبار هندسي",
    open: "فتح الجلسة",
    serverDown: "تعذّر الوصول إلى خادم الجلسة المحلي. شغّله بالأمر python -m aba_demo.live.",
    precomputed: "إعادة تشغيل محسوبة مسبقاً",
    launch: "تشغيل",
    launchAria: (title: string) => `تشغيل ${title}`,
  },
  controls: {
    progress: "تقدّم الجلسة",
    steps: ["فتح المصدر", "تحديد الطفل", "الملاحظة", "المراجعة"],
    open: "فتح المصدر",
    lock: "تثبيت الطفل",
    confirmChild: "تأكيد الطفل",
    start: "بدء الجلسة",
    pause: "إيقاف مؤقت",
    resume: "استئناف",
    end: "إنهاء الجلسة",
    confirmEnd: "تأكيد إنهاء الجلسة",
    again: "تشغيل مرة أخرى",
    newSession: "جلسة جديدة",
  },
  workspace: {
    allScenarios: "كل الجلسات",
    session: "الجلسة",
    breadcrumb: "مسار التنقل",
    details: "تفاصيل الجلسة",
    streamDown: "انقطع بث الأحداث — تُعرض آخر حالة معروفة كقديمة أثناء إعادة الاتصال.",
    lost: "لم تعد هذه الجلسة متاحة على الخادم (ربما أُعيد تشغيله). لا شيء مما يُعرض هنا حالي.",
    newSession: "جلسة جديدة",
    late: (age: string) => `التحليل متأخر ${age} ث عن الزمن الحي. النتائج معلّمة كمتأخرة ولا تُعرض كحالية.`,
    gap: "لم تُحفظ بعض الأحداث أثناء إعادة الاتصال، وقد يكون السجل ناقصاً.",
    dismiss: "إغلاق",
    failed: "فشلت الجلسة",
    ended: "انتهت الجلسة",
    noVideo: "لم يُسجَّل أي فيديو.",
    ledger: (frames: number, dropped: number, sha: string) =>
      `تم التحقق من سجل الإطارات: ${frames} إطاراً، ${dropped} مفقودة · sha256 ${sha}…`,
    noLedger: "لم يُنتج سجل إطارات مكتمل.",
    stats: { videoTime: "زمن الفيديو", observations: "الملاحظات", flags: "العلامات", gaps: "فجوات التحليل", late: "نتائج متأخرة" },
  },
  stage: {
    aria: "تمثيل مرئي مصطنع للمشهد",
    synthetic: "مصدر مصطنع · بلا فيديو",
    replay: "جلسة مسجّلة · تحليل سابق يُعاد تشغيله",
    video: "فيديو الجلسة المسجّلة",
    ended: "انتهت الجلسة · آخر حالة معروفة",
    stale: "قديم · آخر حالة معروفة",
    uncertain: "الهوية غير مؤكدة",
    confirmed: "الطفل مؤكد",
    locked: "الطفل مثبّت",
    videoTime: "زمن الفيديو",
    observations: "ملاحظات",
    analysis: "التحليل",
    resultAge: "عمر النتيجة",
    late: (seconds: string) => `متأخر · ${seconds} ث`,
    overlayUncertain: "الطفل غير ظاهر — الملاحظات موقوفة حتى تتأكد الهوية",
    notOpened: "لم يُفتح المصدر",
    select: "اضغط على الطفل الذي ستلاحظه لتثبيته",
    confirmRecorded: "تم تحديد الطفل عند تحليل هذا التسجيل. أكّده للمتابعة.",
    paused: "متوقف مؤقتاً — ساعة الجلسة والتحليل متوقفان",
    task: "منطقة المهمة",
    seat: "المقعد",
    target: "الطفل",
  },
  home: {
    badge: "تحليل محلي · ملاحظات السياق تستخدم نموذجاً خارجياً",
    heading: "أدلة واضحة من كل جلسة.",
    intro:
    "اختر فيديو الجلسة واضغط على الطفل، ويحدد المساعد ما الذي تغيّر ومتى: الوضعية، والحركة الكبيرة، والاتجاه نحو المهمة، وملاحظات السياق. أنت من يفسّر الأدلة ويتخذ كل قرار.",
    newTitle: "تحليل فيديو جديد",
    newBody:
    "ملف MP4 أو MOV أو WebM من هذا الجهاز. يبقى الفيديو على هذا الجهاز، وتُرسل لقطات قليلة فقط حول اللحظات المرصودة لملاحظات السياق.",
    choose: "اختر فيديو",
    drop: "أو اسحبه وأفلته هنا",
    uploading: (percent: number) => `جارٍ نسخ الفيديو… ${percent}%`,
    resume: "متابعة التحليل الجاري",
    libraryTitle: "الجلسات المحلَّلة",
    libraryBody: "افتح جلسة لمراجعة فيديوها مع اللحظات التي رصدتها القنوات.",
    libraryEmpty: "لا توجد جلسات محلَّلة بعد. حلّل فيديو للبدء.",
    open: "مراجعة",
    moments: (count: number) => `${count} لحظات`,
    flags: (count: number) => `${count} للمراجعة`,
    noMoments: "لم تُرصد لحظات",
    engineeringTitle: "اختبارات هندسية",
    engineeringBody: "سيناريوهات مصطنعة لاختبار واجهة الجلسة الحية. ليست تسجيلات.",
    serverDown: "تعذّر الوصول إلى الخادم المحلي. شغّله بالملف run_live.bat.",
  },
  analysis: {
    title: "تحليل جديد",
    preparing: "جارٍ فتح الفيديو وتحميل النموذج…",
    selectTitle: "اضغط على الطفل الذي ستلاحظه",
    selectBody: "كل شخص ظاهر في الإطار الأول عليه مربع. اضغط داخل مربع الطفل.",
    reselectTitle: "فُقد الطفل — اضغط عليه مرة أخرى",
    reselectBody: (time: string) =>
      `توقف التتبع عند ${time}. اضغط على الطفل للمتابعة، أو تقدّم قليلاً إذا كان الطفل خارج الصورة.`,
    chosen: "تم تحديد الطفل",
    notChosen: "لم يُحدَّد الطفل بعد",
    sessionTitle: "عنوان الجلسة",
    activity: "النشاط في هذا الفيديو",
    activityHint: "يحدد أي اللحظات تُعلَّم للمراجعة، مثل القيام من الجلوس أثناء عمل الطاولة.",
    taskArea: "منطقة المهمة (اختياري)",
    taskHint: "ارسم المنطقة التي تتم فيها المهمة، مثل الطاولة، لقياس الاتجاه نحو المهمة.",
    draw: "ارسم منطقة المهمة",
    drawing: "اسحب على الإطار…",
    clear: "مسح",
    contextNote:
    "ملاحظات السياق: تُرسل لقطات قليلة حول كل لحظة مرصودة إلى DeepSeek عبر OpenRouter (مع رفض جمع البيانات) للحصول على اقتراح قصير.",
    start: "ابدأ التحليل",
    confirm: "تابع مع هذا الطفل",
    skip: "الطفل غير ظاهر — تقدّم ثانيتين",
    continueWithout: "تابع دون سؤالي مرة أخرى",
    running: "جارٍ تحليل الفيديو",
    runningHint: "يمكنك مغادرة هذه الصفحة؛ يستمر التحليل على هذا الجهاز.",
    stages: {
      tracking: "تتبّع الطفل",
      posture: "الوضعية",
      movement: "الحركة الكبيرة",
      orientation: "الاتجاه نحو المهمة",
      context: "ملاحظات السياق",
    },
    status: { pending: "بالانتظار", running: "قيد التنفيذ", done: "اكتمل", skipped: "تم تخطيه", failed: "فشل" },
    notes: {
      no_task_region: "لم تُرسم منطقة المهمة",
      provider_not_configured: "لم يُضبط مفتاح النموذج",
      invalid_config: "ملف مفتاح النموذج غير صالح",
      no_moments: "لا توجد لحظات لوصفها",
      no_local_channel: "لا توجد قناة محلية",
    },
    done: "اكتمل التحليل",
    openReview: "افتح المراجعة",
    failed: "توقف التحليل",
    cancelled: "أُلغي التحليل",
    cancel: "إلغاء التحليل",
    back: "العودة إلى الجلسات",
    reselections: (count: number, max: number) => `مرات إعادة التحديد: ${count} من ${max}`,
    childConfirmed: (percent: number) => `تأكدت هوية الطفل في ${percent}% من الفيديو`,
    errors: {
      child_not_confirmed_enough:
      "تعذّر تتبّع الطفل في جزء كافٍ من الفيديو (خارج الصورة أو لم يُعد تحديده). أعد المحاولة واضغط على الطفل عندما يُطلب منك.",
      no_channel_produced: "تعذّر قياس أي قناة ملاحظة في هذا الفيديو.",
      unsupported_video_type: "نوع ملف غير مدعوم. اختر فيديو MP4 أو MOV أو WebM.",
      video_too_large: "حجم الفيديو أكبر من 8 غيغابايت.",
      empty_upload: "الملف فارغ.",
      video_unreadable: "تعذّر فتح هذا الفيديو. اختر ملف MP4 مسجّلاً بكاميرا أو جوال.",
      analysis_in_progress: "يوجد تحليل آخر جارٍ. أكمله أو ألغِه أولاً.",
      click_ambiguous: "هذه النقطة داخل أكثر من شخص. اضغط على جزء من الطفل لا يغطيه أحد غيره.",
      click_not_on_person: "اضغط داخل مربع الطفل.",
      server_down: "تعذّر الوصول إلى الخادم المحلي.",
    },
    errorCode: (code: string) => `الرمز التقني: ${code}`,
  },
  review: {
    back: "كل الجلسات",
    analysed: (date: string) => `حُلّلت ${date}`,
    duration: "المدة",
    activity: "النشاط",
    childConfirmed: "تأكيد هوية الطفل",
    timeline: "الخط الزمني للجلسة",
    timelineHint: "الأشرطة تبيّن الحالة المقاسة، والعلامات تبيّن اللحظات المرصودة. اضغط في أي مكان للانتقال.",
    channelsTitle: "ماذا رأت كل قناة",
    measured: (percent: number) => `قيست في ${percent}% من الفيديو`,
    contextRead: (read: number, total: number) => `وُصفت ${read} من ${total} لحظات`,
    events: (count: number) => (count === 0 ? "لا أحداث" : count === 1 ? "حدث واحد" : `${count} أحداث`),
    noEventObserved: "تمت المراقبة — لم يُرصد تغيّر",
    now: "الآن",
    notMeasuredNow: "غير مقاسة في هذه اللحظة",
    notAnalysed: "لم تُحلَّل",
    reasons: {
      no_task_region: "لم تُرسم منطقة المهمة",
      provider_not_configured: "لم يُضبط مفتاح النموذج",
      invalid_config: "ملف مفتاح النموذج غير صالح",
      no_moments: "لم تكن هناك لحظات لوصفها",
      no_local_channel: "لا توجد قناة محلية",
    },
    notInSession: "لم تُشغَّل لهذه الجلسة",
    states: { sitting: "جالس", standing: "واقف", toward: "باتجاه المهمة", away: "ملتفت بعيداً" },
    momentsTitle: "اللحظات",
    loadError: "تعذّر تحميل هذه الجلسة.",
  },
  card: {
    title: "للمراجعة",
    during: (channel: string, activity: string) => `${channel} · أثناء ${activity}`,
    from: "من",
    to: "إلى",
    note: "تغيّر مرئي علّمته القواعد المبدئية لهذا النشاط. هو تنبيه لمراجعتك، وليس استنتاجاً عن الانتباه أو النية أو وظيفة السلوك.",
    acknowledge: "تمت المراجعة",
    unavailable: "غير متاح ما دام البث أو الهوية أو التحليل غير حالي.",
    nothing: "لا شيء يحتاج انتباهك الآن.",
  },
  facts: {
    title: "الجلسة",
    scenario: "السيناريو",
    identity: "الهوية",
    notSelected: "لم يُحدَّد",
    confirmed: "مؤكدة",
    uncertain: "غير مؤكدة",
    observations: "الملاحظات",
    precomputed: "محسوبة مسبقاً (ليست حية)",
    synthetic: "مصطنعة",
    recorder: "المسجّل",
    ledger: (frames: number) => `السجل · ${frames} إطاراً`,
    dropped: (frames: number) => ` · ${frames} مفقودة`,
    ledgerHint: "سجل إطارات محاكى: يعدّ الإطارات التي وصلت إلى المسجّل. لا تُخزَّن أي صور.",
    flags: "علامات للمراجعة",
    gaps: "فجوات التحليل",
    p95: "زمن التحليل p95",
    late: "نتائج متأخرة",
  },
  activityCard: {
    title: "نشاط الجلسة",
    hint: "تحدده أنت، وهو الذي يقرر أي اللحظات تُعلَّم للمراجعة، مثل القيام من الجلوس أثناء عمل الطاولة.",
  },
  log: { title: "سجل الأحداث", empty: "ستظهر الأحداث هنا." },
  channels: {
    title: "قنوات الملاحظة",
    note: "علامات مرئية فقط · قواعد مبدئية · ليست تصنيفات سريرية",
    notLoaded: "غير محمّلة لهذه الجلسة",
    noEvent: "لا حدث بعد",
    soFar: (count: number) => `${count} حتى الآن`,
    aria: (channel: string, count: number | null) => `${channel}: ${count === null ? "غير محمّلة" : `${count} أحداث`}`,
  },
  strip: {
    title: "شريط الجلسة",
    empty: "ستظهر اللحظات المؤكدة هنا عندما تصل إليها الجلسة.",
    emptyReview: "لم تُرصد أي لحظة في هذه الجلسة. توضح المسارات أعلاه ما قاسته كل قناة.",
    suggestion: "مقترح من نموذج",
    watch: "شاهد",
    watchAria: (time: string) => `شاهد اللحظة عند ${time}`,
    before: "قبل",
    after: "بعد",
    modelSees: "النموذج يرى الطفل",
    experimental: "تجريبي",
    agrees: "يتفق مع القياس",
    disagrees: "يحتاج تحقق: النموذج يراه بشكل مختلف",
    checkBadge: "يحتاج تحقق",
  },
  channel: {
    posture: "الوضعية",
    movement: "الحركة الكبيرة",
    orientation: "الاتجاه نحو المهمة",
    context: "السياق",
  },
  basis: {
    posture: "الجلوس ↔ الوقوف من مفاصل ساقي الطفل نفسه",
    movement: "انتقل مركز الجسم أكثر من طول جذع",
    orientation: "الرأس ملتفت بعيداً عن منطقة المهمة المرسومة",
    context: "ملاحظة نموذج على لحظات محددة · اقتراح فقط",
  },
  kind: {
    sit_to_stand: "قام من الجلوس",
    stand_to_sit: "جلس",
    large_movement: "حركة كبيرة",
    turned_away_from_task: "التفت بعيداً عن المهمة",
    turned_back_to_task: "عاد باتجاه المهمة",
    context_note: "ملاحظة سياق",
  },
  level: { flag: "للمراجعة", info: "معلومة" },
  origin: { measured: "قياس محلي", suggested: "مقترح من نموذج" },
  activity: { table: "عمل الطاولة", movement: "نشاط حركي", break: "استراحة" },
  sessionState: {
    created: "أُنشئت",
    previewing: "معاينة",
    target_selected: "تم تحديد الطفل",
    running: "جارية",
    paused: "متوقفة مؤقتاً",
    stopping: "قيد الإيقاف",
    completed: "اكتملت",
    failed: "فشلت",
  },
  termination: {
    user_stop: "أوقفها المعالج",
    source_eof: "انتهى المصدر",
    source_disconnected: "انقطع المصدر",
    worker_failed: "فشل عامل التحليل",
    server_shutdown: "توقف الخادم",
    user_left: "غادرها المعالج",
    recorder_failed: "فشل المسجّل",
  },
  error: {
    provider_failed: "التحليل غير متاح لإطار",
    source_disconnected: "انقطع مصدر الفيديو",
    worker_failed: "فشل عامل التحليل",
    recorder_failed: "فشل المسجّل — لا يوجد تسجيل مكتمل",
  },
  detail: {
    child_location: { at_table: "عند الطاولة", away_from_table: "بعيد عن الطاولة", walking: "يتنقّل", on_floor: "على الأرض" },
    child_handling_material: { yes: "يمسك أداة", no: "لا يمسك أداة" },
    notSeparable: "تعذّر فصل جسم الطفل عن البالغ",
    child_position_after: {
      seated: "جالس", standing: "واقف", walking: "يمشي", on_floor: "على الأرض", held_by_adult: "يحمله بالغ",
    },
    adult_movement: {
      moved_closer: "البالغ اقترب", moved_away: "البالغ ابتعد", stayed: "البالغ بقي في مكانه",
      no_adult_visible: "لا يظهر بالغ",
    },
    materials_change: { added: "أُضيفت أدوات", removed: "أُزيلت أدوات" },
  },
  timeline: {
    identityConfirmed: "تأكدت هوية الطفل",
    identityUncertain: "هوية الطفل غير مؤكدة",
    suppressed: "الملاحظات موقوفة",
    flag: (kind: string) => `${kind} — للمراجعة`,
    flagDetail: "علامة من القواعد المبدئية",
    activity: (activity: string) => `النشاط: ${activity}`,
    activityDetail: "يسري من هذه اللحظة",
    errorDetail: "لم تُنتج أي ملاحظة",
  },
};

export const STRINGS: Record<Language, Strings> = { en, ar };

/** Arabic titles for the server's scenarios; English comes from the server itself. */
export const SCENARIO_TEXT: Partial<Record<Language, Record<string, { title: string; summary: string }>>> = {
  ar: {
    "table-routine": { title: "روتين الطاولة", summary: "عمل هادئ على الطاولة مع تغيّرات قصيرة. سيناريو مصطنع." },
    "leaves-seat": { title: "مغادرة المقعد", summary: "الطفل يقوم من مقعده أثناء العمل على الطاولة. سيناريو مصطنع." },
    "brief-occlusion": { title: "اختفاء قصير", summary: "الطفل يختفي لحظات فتصبح الهوية غير مؤكدة. سيناريو مصطنع." },
    "partial-visibility": { title: "ظهور جزئي", summary: "بعض أجزاء الجسم غير ظاهرة، فلا يُرصد ما لا يُرى. سيناريو مصطنع." },
    "analysis-failures": { title: "أعطال التحليل", summary: "فشل التحليل في بعض الإطارات دون اختلاق نتائج. سيناريو مصطنع." },
    "source-disconnect": { title: "انقطاع المصدر", summary: "انقطاع مصدر الفيديو وإنهاء الجلسة. سيناريو مصطنع." },
    "slow-analysis": { title: "تحليل بطيء", summary: "التحليل يتأخر عن الزمن الحي فتُعلَّم النتائج متأخرة. سيناريو مصطنع." },
    "recorder-failure": { title: "فشل المسجّل", summary: "فشل المسجّل دون ادعاء تسجيل مكتمل. سيناريو مصطنع." },
    "precomputed-replay": { title: "إعادة تشغيل جلسة مسجّلة", summary: "تحليل سابق لفيديو مسجّل يُعاد تشغيله بالزمن الحقيقي، بعد التحقق من مطابقته للفيديو." },
  },
};

export function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Structured log label, rendered in the current language. */
export type TimelineLabel =
  | { type: "state"; state: SessionState; reason?: string }
  | { type: "identity"; identity: Identity }
  | { type: "flag"; kind: string }
  | { type: "activity"; activity: Activity }
  | { type: "error"; code: string };

export function timelineText(item: { label: TimelineLabel }, s: Strings): { title: string; detail?: string } {
  const label = item.label;
  switch (label.type) {
    case "state":
      return {
        title: s.sessionState[label.state],
        detail: label.reason ? s.termination[label.reason] ?? titleCase(label.reason) : undefined,
      };
    case "identity":
      return label.identity === "confirmed"
        ? { title: s.timeline.identityConfirmed }
        : { title: s.timeline.identityUncertain, detail: s.timeline.suppressed };
    case "flag":
      return { title: s.timeline.flag(s.kind[label.kind] ?? titleCase(label.kind)), detail: s.timeline.flagDetail };
    case "activity":
      return { title: s.timeline.activity(s.activity[label.activity]), detail: s.timeline.activityDetail };
    case "error":
      return { title: s.error[label.code] ?? titleCase(label.code), detail: s.timeline.errorDetail };
  }
}

/** Closed-enum context details as text; unclear answers are left out. */
export function contextDetails(details: Record<string, string>, s: Strings): string {
  if (details.child_separable === "no") return s.detail.notSeparable;
  return [
    s.detail.child_location[details.child_location ?? ""],
    s.detail.child_handling_material[details.child_handling_material ?? ""],
    s.detail.child_position_after[details.child_position_after ?? ""],
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Context v2 (before / during / after) as display lines; null for v1 notes. */
export interface ContextStory {
  before: string;
  after: string;
  position: string;
  opinion: "agrees" | "disagrees" | null;
  experimental: { before: string; after: string };
}

export function contextStory(details: Record<string, string>, s: Strings): ContextStory | null {
  if (!("second_opinion" in details)) return null;
  const separable = details.child_separable !== "no";
  const pick = (map: Record<string, string>, key: string) => (separable ? map[details[key] ?? ""] ?? "" : "");
  const opinion = details.second_opinion;
  return {
    before: pick(s.detail.adult_movement, "adult_movement_before"),
    after: pick(s.detail.adult_movement, "adult_movement_after"),
    position: separable ? pick(s.detail.child_position_after, "child_position_after") : s.detail.notSeparable,
    opinion: opinion === "agrees" || opinion === "disagrees" ? opinion : null,
    // Material changes are shown only when one is reported, marked experimental (not yet validated).
    experimental: {
      before: pick(s.detail.materials_change, "materials_change_before"),
      after: pick(s.detail.materials_change, "materials_change_after"),
    },
  };
}

/** Scenario title in the current language (server titles are English). */
export function scenarioTitle(scenario: { id: string; title: string } | undefined, language: Language): string | undefined {
  if (!scenario) return undefined;
  return SCENARIO_TEXT[language]?.[scenario.id]?.title ?? scenario.title;
}

const STORAGE_KEY = "aba-live-language";

export function readStoredLanguage(storage: Pick<Storage, "getItem"> | null): Language {
  try {
    const value = storage?.getItem(STORAGE_KEY);
    return value === "ar" || value === "en" ? value : "en";
  } catch {
    return "en";
  }
}

function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

interface I18nValue {
  language: Language;
  s: Strings;
  toggle: () => void;
}

const I18nContext = createContext<I18nValue>({ language: "en", s: en, toggle: () => {} });

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => readStoredLanguage(browserStorage()));
  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = STRINGS[language].dir;
    try {
      browserStorage()?.setItem(STORAGE_KEY, language);
    } catch {
      // A blocked store only means the choice is not remembered.
    }
  }, [language]);
  const toggle = useCallback(() => setLanguage((current) => (current === "en" ? "ar" : "en")), []);
  const value = useMemo(() => ({ language, s: STRINGS[language], toggle }), [language, toggle]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  return useContext(I18nContext);
}
