from trytond.pool import Pool


def apply_quality_test_values(tests, qualitative_map=None,
        quantitative_map=None, key='line', require_all=False,
        validate=True, validate_success_only=False):
    pool = Pool()
    QualityTest = pool.get('quality.test')
    QualitativeLine = pool.get('quality.qualitative.test.line')
    QuantitativeLine = pool.get('quality.quantitative.test.line')
    QualitativeValue = pool.get('quality.qualitative.value')

    qualitative_map = qualitative_map or {}
    quantitative_map = quantitative_map or {}
    qualitative_to_save = []
    quantitative_to_save = []

    for test in tests:
        if test.state not in {'draft', 'confirmed'}:
            continue
        for line in test.qualitative_lines:
            line_key = _get_quality_line_key(line, key)
            raw_value = (qualitative_map.get(line_key) or '').strip()
            if not raw_value:
                if require_all:
                    return 'missing_required'
                continue
            try:
                line.value = QualitativeValue.browse([int(raw_value)])[0]
            except (TypeError, ValueError, IndexError):
                return 'invalid_qualitative'
            qualitative_to_save.append(line)
        for line in test.quantitative_lines:
            line_key = _get_quality_line_key(line, key)
            raw_value = (quantitative_map.get(line_key) or '').strip()
            if raw_value == '':
                if require_all:
                    return 'missing_required'
                continue
            try:
                line.value = float(raw_value)
            except (TypeError, ValueError):
                return 'invalid_number'
            if not line.unit and line.unit_range:
                line.unit = line.unit_range
            quantitative_to_save.append(line)

    if qualitative_to_save:
        QualitativeLine.save(qualitative_to_save)
    if quantitative_to_save:
        QuantitativeLine.save(quantitative_to_save)

    if not validate:
        return None

    tests_to_validate = [
        test for test in tests
        if test.state in {'draft', 'confirmed'}
    ]
    if tests_to_validate:
        drafts = [
            test for test in tests_to_validate
            if test.state == 'draft'
        ]
        if drafts:
            QualityTest.confirmed(drafts)
        refreshed_tests = QualityTest.browse([
                test.id for test in tests_to_validate
            ])
        if validate_success_only:
            refreshed_tests = [
                test for test in refreshed_tests if test.success
            ]
        if refreshed_tests:
            QualityTest.manager_validate(refreshed_tests)
    return None


def create_manual_quality_tests(document, templates, company=None,
        qualitative_map=None, quantitative_map=None, test_date=None,
        avoid_existing=True, validate=True):
    pool = Pool()
    QualityTest = pool.get('quality.test')

    if not document or not templates:
        return []

    existing_tests = []
    existing_template_ids = set()
    if avoid_existing:
        existing_tests = QualityTest.search([
                ('document', '=', document),
            ], order=[('id', 'ASC')])
        existing_template_ids = {
            template.id
            for test in existing_tests
            for template in test.templates
        }

    created_tests = []
    for template in templates:
        if template.id in existing_template_ids:
            continue
        created_tests.append(QualityTest(
                test_date=test_date,
                document=document,
                templates=[template],
                company=company,
                ))
    if created_tests:
        QualityTest.save(created_tests)
        QualityTest.apply_templates(created_tests)

    manual_template_ids = {template.id for template in templates}
    tests = [
        test for test in existing_tests + created_tests
        if {template.id for template in test.templates} & manual_template_ids
    ]
    apply_quality_test_values(
        tests, qualitative_map=qualitative_map,
        quantitative_map=quantitative_map, key='template_line',
        validate=validate)
    return tests


def _get_quality_line_key(line, key):
    if key == 'template_line':
        template_line = getattr(line, 'template_line', None)
        return getattr(template_line, 'id', None)
    return getattr(line, 'id', None)
