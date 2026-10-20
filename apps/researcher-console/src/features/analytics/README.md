# P4 — Analytics UI feature

`client.ts` exports the typed, mountable API client for the shared researcher console. It uses the frozen AnalysisRequest/AnalysisResult v1 contracts and same-origin credentials so the shared app can supply its normal authentication/session behavior. The console owner can import `createAnalyticsClient` into the shared navigation and screens.

The feature does not host a standalone HTML demo or accept raw FeatureRecords from the browser. P4 analysis is requested by study/version and the API retrieves canonical records through the injected P3 provider. The API result owns modality, sample size, quality/missingness, results and limitations; the UI must present those without calculating or redefining P3 measurement features.
