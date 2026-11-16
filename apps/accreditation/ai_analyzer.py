"""
AI Quality Analyzer & Gap Detection Engine (المساعد الذكي لتحليل الدراسة الذاتية واكتشاف الفجوات واقتراح مسودة تقرير المقارنة التحليلي)
Analyzes Self-Study Reports (SSR), Digital Evidences (SHA-256), External Reviewer Rubric Scores,
Site Visit Inspections, and Institution Replies to detect quality gaps and auto-generate
the Secretariat's Analytical Comparison Report draft.
"""
from django.utils import timezone
from apps.standards.models import StandardCategory, RubricEvaluationLevel
from apps.accreditation.models import SelfStudyIndicatorResponse


SSR_NUMERIC_MAP = {
    SelfStudyIndicatorResponse.ComplianceLevel.MET: 3.0,
    SelfStudyIndicatorResponse.ComplianceLevel.PARTIALLY_MET: 1.5,
    SelfStudyIndicatorResponse.ComplianceLevel.INSUFFICIENT_EVIDENCE: 0.5,
    SelfStudyIndicatorResponse.ComplianceLevel.NOT_MET: 0.0,
}

EXT_NUMERIC_MAP = {
    RubricEvaluationLevel.FULLY_MET: 3.0,
    RubricEvaluationLevel.SUBSTANTIALLY_MET: 2.25,
    RubricEvaluationLevel.PARTIALLY_MET: 1.5,
    RubricEvaluationLevel.NOT_MET: 0.0,
}


class AIQualityAnalyzer:
    """
    Intelligent Quality Assurance & Accreditation Diagnostic Engine for CAQA Portal.
    """

    @classmethod
    def analyze_application(cls, application):
        self_study = getattr(application, 'self_study_report', None)
        ext_report = getattr(application, 'external_report', None)
        site_visit = getattr(application, 'site_visit', None)
        desk_review = application.desk_reviews.order_by('-reviewed_at').first()

        categories = StandardCategory.objects.filter(
            track=application.track
        ).prefetch_related('indicators').order_by('order')

        ssr_map = {}
        if self_study:
            for resp in self_study.indicator_responses.select_related('indicator').all():
                ssr_map[resp.indicator_id] = resp

        ext_scores_map = {}
        for sc in application.indicator_scores.select_related('indicator', 'evaluator').all():
            ext_scores_map.setdefault(sc.indicator_id, []).append(sc)

        evidences_by_ind = {}
        all_evidences = list(application.evidences.select_related('indicator').all())
        for ev in all_evidences:
            evidences_by_ind.setdefault(ev.indicator_id, []).append(ev)

        # 1. Self-Study Narrative Diagnostics
        narrative_sections = [
            ('الملخص التنفيذي للدراسة الذاتية', getattr(self_study, 'executive_summary', '') if self_study else ''),
            ('الخلفية التاريخية والتعريفية', getattr(self_study, 'historical_background', '') if self_study else ''),
            ('لجنة التقييم الذاتي الداخلية', getattr(self_study, 'internal_committee_names', '') if self_study else ''),
            ('المنهجية وآليات جمع البيانات', getattr(self_study, 'methodology', '') if self_study else ''),
            ('أبرز نقاط القوة الداخلية', getattr(self_study, 'strengths_overview', '') if self_study else ''),
            ('التحديات ومواطن التحسين', getattr(self_study, 'weaknesses_and_challenges', '') if self_study else ''),
        ]
        narrative_diagnostics = []
        completed_narratives = 0
        for label, text in narrative_sections:
            clean_text = (text or '').strip()
            word_count = len(clean_text.split()) if clean_text else 0
            if word_count >= 8:
                status = 'COMPLETE'
                status_label = 'مكتمل ووافٍ'
                completed_narratives += 1
            elif word_count > 0:
                status = 'BRIEF'
                status_label = 'مقتضب (يحتاج تفصيلاً أعمق)'
                completed_narratives += 0.5
            else:
                status = 'MISSING'
                status_label = 'غير مستوفى (فارغ)'
            narrative_diagnostics.append({
                'label': label,
                'word_count': word_count,
                'status': status,
                'status_label': status_label,
            })

        narrative_score_pct = round((completed_narratives / len(narrative_sections)) * 100, 1) if narrative_sections else 0.0

        # 2. Indicator-by-Indicator & Standard-by-Standard Gap Analysis
        detected_gaps = []
        standard_diagnostics = []
        total_indicators = 0
        indicators_with_evidence = 0
        all_ssr_vals = []
        all_ext_vals = []
        abs_diffs = []
        core_unmet_count = 0

        for cat in categories:
            cat_inds = list(cat.indicators.all())
            cat_ssr_vals = []
            cat_ext_vals = []
            cat_gaps_count = 0
            ind_rows = []

            for ind in cat_inds:
                total_indicators += 1
                ssr_resp = ssr_map.get(ind.id)
                ext_list = ext_scores_map.get(ind.id, [])
                ind_evs = evidences_by_ind.get(ind.id, [])

                if ind_evs:
                    indicators_with_evidence += 1

                ssr_val = SSR_NUMERIC_MAP.get(ssr_resp.compliance_level, None) if ssr_resp else None
                ssr_label = ssr_resp.get_compliance_level_display() if ssr_resp else 'لم يُقيّم ذاتياً'

                if ext_list:
                    ext_vals = [EXT_NUMERIC_MAP.get(x.score_level, 0.0) for x in ext_list]
                    ext_val = round(sum(ext_vals) / len(ext_vals), 2)
                    ext_label = ext_list[0].get_score_level_display()
                    ext_weaknesses = " | ".join(filter(None, [x.weaknesses for x in ext_list]))
                    ext_strengths = " | ".join(filter(None, [x.strengths for x in ext_list]))
                else:
                    ext_val = None
                    ext_label = 'لم يُقيّم خارجياً بعد'
                    ext_weaknesses = ''
                    ext_strengths = ''

                if ssr_val is not None:
                    cat_ssr_vals.append(ssr_val)
                    all_ssr_vals.append(ssr_val)
                if ext_val is not None:
                    cat_ext_vals.append(ext_val)
                    all_ext_vals.append(ext_val)

                diff = None
                if ssr_val is not None and ext_val is not None:
                    diff = round(ssr_val - ext_val, 2)
                    abs_diffs.append(abs(diff))

                # Detect specific gaps for this indicator
                ind_gap_flags = []

                # Gap Type 1: Unverified Claim (Claimed MET without Digital Evidence)
                if ssr_resp and ssr_resp.compliance_level == SelfStudyIndicatorResponse.ComplianceLevel.MET and not ind_evs:
                    cat_gaps_count += 1
                    gap_msg = f"ادعاء استيفاء كامل للمؤشر ({ind.code}: {ind.title}) في الدراسة الذاتية دون إرفاق أي وثيقة شاهد رقمية مؤيدة."
                    ind_gap_flags.append(gap_msg)
                    detected_gaps.append({
                        'severity': 'HIGH',
                        'severity_label': 'فجوة توثيق وشواهد عالية',
                        'badge_class': 'bg-warning text-dark',
                        'standard_code': cat.code,
                        'indicator_code': ind.code,
                        'title': f"غياب الشواهد الرقمية المؤيدة للمؤشر ({ind.code})",
                        'description': gap_msg,
                        'recommendation': 'إلزام المؤسسة برفع الشواهد الرقمية الموثقة ببصمة SHA-256 أو تخفيض درجة المؤشر.',
                    })

                # Gap Type 2: Overestimation / Discrepancy between Self-Study & External Review
                if diff is not None and diff >= 1.0:
                    cat_gaps_count += 1
                    gap_msg = (
                        f"تباين جوهري في المؤشر ({ind.code}: {ind.title})؛ قيّمته المؤسسة بـ ({ssr_label}: {ssr_val}/3) "
                        f"بينما قيّمته لجنة المراجعة الخارجية بـ ({ext_label}: {ext_val}/3) بفارق (+{diff} درجة)."
                    )
                    ind_gap_flags.append(gap_msg)
                    detected_gaps.append({
                        'severity': 'CRITICAL' if ind.is_core_standard else 'HIGH',
                        'severity_label': 'تباين حاد في معيار جوهري' if ind.is_core_standard else 'مبالغة في التقييم الذاتي',
                        'badge_class': 'bg-danger' if ind.is_core_standard else 'bg-warning text-dark',
                        'standard_code': cat.code,
                        'indicator_code': ind.code,
                        'title': f"فجوة تقييم بين الدراسة الذاتية والمحكمين ({ind.code})",
                        'description': gap_msg + (f" ملاحظات المحكمين: {ext_weaknesses}" if ext_weaknesses else ""),
                        'recommendation': 'اعتماد تقدير لجنة المراجعة الخارجية وتضمين المؤشر في خطة التحسين المشروطة.',
                    })

                # Gap Type 3: Core Standard Deficiency
                if ind.is_core_standard and ((ext_val is not None and ext_val < 2.0) or (ext_val is None and ssr_val is not None and ssr_val < 2.0)):
                    core_unmet_count += 1
                    cat_gaps_count += 1
                    gap_msg = f"قصور في استيفاء المؤشر الجوهري الحاسم ({ind.code}: {ind.title}) بدرجة ({ext_val if ext_val is not None else ssr_val}/3)."
                    ind_gap_flags.append(gap_msg)
                    detected_gaps.append({
                        'severity': 'CRITICAL',
                        'severity_label': 'خطر حرج (معيار جوهري)',
                        'badge_class': 'bg-danger',
                        'standard_code': cat.code,
                        'indicator_code': ind.code,
                        'title': f"عدم استيفاء معيار جوهري حاسم ({ind.code})",
                        'description': gap_msg,
                        'recommendation': 'اشتراط معالجة فورية ضمن خطة التحسين المستمر قبل منح الاعتماد الكامل.',
                    })

                # Gap Type 4: Self-identified partial/unmet indicator lacking corrective action plan
                if ssr_resp and ssr_resp.compliance_level in [
                    SelfStudyIndicatorResponse.ComplianceLevel.PARTIALLY_MET,
                    SelfStudyIndicatorResponse.ComplianceLevel.NOT_MET,
                ] and not (ssr_resp.corrective_actions or '').strip():
                    cat_gaps_count += 1
                    gap_msg = f"أقرت المؤسسة بعدم اكتمال المؤشر ({ind.code}) دون تدوين إجراءات تصحيحية أو موعد مستهدف للتحسين."
                    ind_gap_flags.append(gap_msg)
                    detected_gaps.append({
                        'severity': 'MODERATE',
                        'severity_label': 'فجوة خطة تحسين',
                        'badge_class': 'bg-info text-dark',
                        'standard_code': cat.code,
                        'indicator_code': ind.code,
                        'title': f"نقص الخطة التصحيحية للمؤشر ({ind.code})",
                        'description': gap_msg,
                        'recommendation': 'استكمال مصفوفة الإجراءات التصحيحية وتحديد المسؤول والجدول الزمني.',
                    })

                ind_rows.append({
                    'indicator': ind,
                    'ssr_label': ssr_label,
                    'ssr_val': ssr_val,
                    'ext_label': ext_label,
                    'ext_val': ext_val,
                    'diff': diff,
                    'evidences_count': len(ind_evs),
                    'ext_strengths': ext_strengths,
                    'ext_weaknesses': ext_weaknesses,
                    'gap_flags': ind_gap_flags,
                })

            avg_cat_ssr = round(sum(cat_ssr_vals) / len(cat_ssr_vals), 2) if cat_ssr_vals else None
            avg_cat_ext = round(sum(cat_ext_vals) / len(cat_ext_vals), 2) if cat_ext_vals else None
            avg_cat_diff = round(avg_cat_ssr - avg_cat_ext, 2) if (avg_cat_ssr is not None and avg_cat_ext is not None) else None

            if avg_cat_ext is not None:
                cat_pct = round((avg_cat_ext / 3.0) * 100, 1)
            elif avg_cat_ssr is not None:
                cat_pct = round((avg_cat_ssr / 3.0) * 100, 1)
            else:
                cat_pct = 0.0

            standard_diagnostics.append({
                'category': cat,
                'indicators_count': len(cat_inds),
                'avg_ssr': avg_cat_ssr,
                'avg_ext': avg_cat_ext,
                'avg_diff': avg_cat_diff,
                'compliance_pct': cat_pct,
                'gaps_count': cat_gaps_count,
                'indicators': ind_rows,
            })

        # 3. Site Visit & Facility Safety Diagnostics
        site_visit_summary = {
            'conducted': False,
            'facilities_count': 0,
            'unsafe_facilities_count': 0,
            'interviews_count': 0,
            'audits_count': 0,
        }
        if site_visit:
            facilities = list(site_visit.facility_inspections.all())
            interviews = list(site_visit.interviews.all())
            audits = list(site_visit.academic_audits.all())
            unsafe_facs = [f for f in facilities if not f.safety_compliance]
            site_visit_summary = {
                'conducted': True,
                'status_display': site_visit.get_status_display(),
                'facilities_count': len(facilities),
                'unsafe_facilities_count': len(unsafe_facs),
                'interviews_count': len(interviews),
                'audits_count': len(audits),
            }
            for uf in unsafe_facs:
                detected_gaps.append({
                    'severity': 'CRITICAL',
                    'severity_label': 'ملاحظة سلامة ميدانية حرجة',
                    'badge_class': 'bg-danger',
                    'standard_code': 'الزيارة الميدانية',
                    'indicator_code': uf.get_category_display(),
                    'title': f"ملاحظة أمن وسلامة في المرفق ({uf.facility_name})",
                    'description': f"رصد فريق الزيارة الميدانية عدم استيفاء متطلبات الأمن والسلامة في ({uf.facility_name}): {uf.detailed_observations}",
                    'recommendation': 'إلزام المؤسسة باستيفاء اشتراطات السلامة المهنية والمعملية فوراً.',
                })

        # 4. Overall AI Scores Calculation
        evidence_coverage_pct = round((indicators_with_evidence / total_indicators) * 100, 1) if total_indicators else 100.0
        verified_evidences_count = sum(1 for e in all_evidences if e.sha256_hash)

        overall_ssr_avg = round(sum(all_ssr_vals) / len(all_ssr_vals), 2) if all_ssr_vals else 0.0
        overall_ext_avg = round(sum(all_ext_vals) / len(all_ext_vals), 2) if all_ext_vals else overall_ssr_avg

        if abs_diffs:
            mean_abs_diff = sum(abs_diffs) / len(abs_diffs)
            alignment_index = round(max(0.0, 100.0 - (mean_abs_diff / 3.0) * 100.0), 1)
        else:
            alignment_index = 85.0 if all_ssr_vals else 0.0

        # Weighted Readiness Score (0 - 100%)
        ext_or_ssr_pct = (overall_ext_avg / 3.0) * 100.0 if (all_ext_vals or all_ssr_vals) else 50.0
        readiness_score = round(
            (ext_or_ssr_pct * 0.55) +
            (narrative_score_pct * 0.15) +
            (min(100.0, evidence_coverage_pct + (20.0 if all_evidences else 0.0)) * 0.15) +
            (alignment_index * 0.15),
            1
        )

        # Determine AI Recommended Decision
        critical_gaps_count = sum(1 for g in detected_gaps if g['severity'] == 'CRITICAL')
        if readiness_score >= 80.0 and critical_gaps_count == 0 and core_unmet_count == 0:
            ai_recommendation_code = 'FULL_ACCREDITATION'
            ai_recommendation_label = 'منح الاعتماد الأكاديمي الكامل (لمدة 5 سنوات)'
            ai_badge_class = 'bg-success'
        elif readiness_score >= 55.0:
            ai_recommendation_code = 'CONDITIONAL_ACCREDITATION'
            ai_recommendation_label = 'منح الاعتماد المشروط مع إلزام المؤسسة بخطة تحسين مستمر'
            ai_badge_class = 'bg-warning text-dark'
        else:
            ai_recommendation_code = 'POSTPONE_OR_DENY'
            ai_recommendation_label = 'تأجيل منح الاعتماد لحين استيفاء الفجوات الجوهرية الحرجة'
            ai_badge_class = 'bg-danger'

        # 5. Synthesize Structured Draft for Secretariat Comparison Report
        inst_name = application.institution.name
        prog_part = f" - برنامج ({application.program.name})" if application.program else ""
        reply_text = (ext_report.institution_reply_text or '').strip() if ext_report else ''
        ext_rec_display = ext_report.get_final_recommendation_display() if ext_report else 'قيد التقييم'

        gaps_bullet_lines = []
        for idx, g in enumerate(detected_gaps[:8], start=1):
            gaps_bullet_lines.append(f"  {idx}. [{g['severity_label']}] {g['title']}: {g['description']}")
        if not gaps_bullet_lines:
            gaps_bullet_lines.append("  - لم يرصد المساعد الذكي أي فجوات حرجة أو تباينات حادة بين التقييم الذاتي وتقييم لجنة المراجعة الخارجية.")

        if reply_text:
            reply_eval_paragraph = (
                f"قدمت المؤسسة ردها الرسمي على مسودة تقرير المراجعة الخارجية بتاريخ "
                f"({ext_report.institution_reply_date.strftime('%Y-%m-%d') if ext_report.institution_reply_date else 'مؤخراً'})، "
                f"وتضمن الرد: «{reply_text[:220]}». وبموجب التحليل الذكي، فإن رد المؤسسة يعالج جزءاً من الملاحظات الإجرائية "
                f"مع بقاء الحاجة لمتابعة المؤشرات ذات الفجوات عبر خطة التحسين الدورية."
            )
        else:
            reply_eval_paragraph = "لم ترد مذكرة اعتراض أو ملاحظات جوهرية إضافية من المؤسسة تغير من نتائج التحقق الميداني."

        draft_comparison_title = (
            f"تقرير المقارنة التحليلي المدعوم بالتحليل الذكي (AI Quality Analyzer) - {application.application_number}"
        )

        draft_analytical_summary = (
            f"أولاً: الملخص التنفيذي ومؤشرات الجاهزية الذكية (AI Quality Diagnostics):\n"
            f"- المؤسسة والبرنامج: {inst_name}{prog_part} | رقم الطلب: ({application.application_number}).\n"
            f"- مؤشر الجاهزية الكلي للاعتماد (AI Readiness Score): ({readiness_score}%) | مؤشر التوافق والمصداقية (Alignment Index): ({alignment_index}%).\n"
            f"- متوسط التقييم الذاتي للمؤسسة: ({overall_ssr_avg} / 3.00) مقابل متوسط تقييم لجنة المراجعة الخارجية: ({overall_ext_avg} / 3.00).\n"
            f"- تغطية الشواهد الرقمية الموثقة ببصمة SHA-256: ({len(all_evidences)} وثيقة شاهد، بنسبة تغطية {evidence_coverage_pct}% للمؤشرات).\n\n"
            f"ثانياً: أبرز الفجوات والتباينات المكتشفة آلياً بين الدراسة الذاتية والمراجعة الخارجية:\n"
            + "\n".join(gaps_bullet_lines) + "\n\n"
            f"ثالثاً: تقييم الزيارة الميدانية ورد المؤسسة (حق الرد):\n"
            f"- شملت الزيارة الميدانية معاينة ({site_visit_summary['facilities_count']}) مرفقاً ومعملاً، وإجراء ({site_visit_summary['interviews_count']}) مقابلة مع أصحاب المصلحة، و({site_visit_summary['audits_count']}) سجل تدقيق أكاديمي.\n"
            f"- {reply_eval_paragraph}\n\n"
            f"رابعاً: الرأي الفني المحايد للأمانة العامة والتوصية المقترحة لمجلس الإدارة:\n"
            f"- توصية لجنة المراجعة الخارجية: ({ext_rec_display}).\n"
            f"- توصية المساعد الذكي والأمانة العامة المرفوعة لمجلس الإدارة: ({ai_recommendation_label})، "
            f"مع متابعة التوصيات التصحيحية عبر الإدارة العامة للجودة والرقابة اللاحقة."
        )

        return {
            'generated_at': timezone.now(),
            'readiness_score': readiness_score,
            'alignment_index': alignment_index,
            'narrative_score_pct': narrative_score_pct,
            'evidence_coverage_pct': evidence_coverage_pct,
            'total_evidences_count': len(all_evidences),
            'verified_evidences_count': verified_evidences_count,
            'overall_ssr_avg': overall_ssr_avg,
            'overall_ext_avg': overall_ext_avg,
            'total_indicators': total_indicators,
            'critical_gaps_count': critical_gaps_count,
            'total_gaps_count': len(detected_gaps),
            'core_unmet_count': core_unmet_count,
            'ai_recommendation_code': ai_recommendation_code,
            'ai_recommendation_label': ai_recommendation_label,
            'ai_badge_class': ai_badge_class,
            'narrative_diagnostics': narrative_diagnostics,
            'standard_diagnostics': standard_diagnostics,
            'detected_gaps': detected_gaps,
            'site_visit_summary': site_visit_summary,
            'desk_review': desk_review,
            'draft_comparison_title': draft_comparison_title,
            'draft_analytical_summary': draft_analytical_summary,
        }
