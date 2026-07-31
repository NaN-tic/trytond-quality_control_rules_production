from datetime import datetime

from trytond.model import ModelView, fields
from trytond.pool import Pool, PoolMeta
from trytond.transaction import Transaction

from .quality import apply_quality_test_values, create_manual_quality_tests

__all__ = ['register']


def _get_company_context(record):
    company = record.company
    company_id = company.id
    return {
        'company': company_id,
        'companies': [company_id],
    }


def _get_work_product_template(work):
    return work.production.product.template


class QualityRuleDocumentMixin:
    __slots__ = ()

    quality_tests = fields.One2Many(
        'quality.test', 'document', 'Quality Tests', readonly=True)

    def get_quality_rule_models(self):
        return self.__name__, self.__name__

    def get_quality_rule_company(self):
        return self.company

    def get_quality_rule_operation(self):
        return self.operation

    def get_quality_templates(self, creation_moment, state=None):
        QualityControlRule = Pool().get('quality.control.rule')
        document_model, trigger_document_model = self.get_quality_rule_models()
        return QualityControlRule.get_quality_templates(
            document_model=document_model,
            trigger_document_model=trigger_document_model,
            creation_moment=creation_moment,
            state=state,
            company=self.get_quality_rule_company(),
            operation=self.get_quality_rule_operation(),
            product=self.get_quality_test_product())

    def has_quality_rules(self, creation_moment, state=None):
        return bool(self.get_quality_templates(
                creation_moment, state=state))

    def ensure_quality_tests(self, creation_moment, state=None):
        if not self.has_quality_rules(creation_moment, state=state):
            return []
        QualityControlRule = Pool().get('quality.control.rule')
        document_model, trigger_document_model = self.get_quality_rule_models()
        with Transaction().set_context(**_get_company_context(self)):
            return QualityControlRule.create_quality_tests(
                self,
                document_model=document_model,
                trigger_document_model=trigger_document_model,
                creation_moment=creation_moment,
                state=state,
                company=self.get_quality_rule_company(),
                operation=self.get_quality_rule_operation(),
                product=self.get_quality_test_product())


class Work(QualityRuleDocumentMixin, metaclass=PoolMeta):
    __name__ = 'production.work'

    def get_quality_test_product(self):
        return _get_work_product_template(self)

    def get_quality_test_template_ids(self, state=None):
        template_ids = {
            template.id
            for template in self.get_quality_templates('create')
        }
        if state:
            template_ids.update(
                template.id
                for template in self.get_quality_templates('state', state=state))
        return template_ids

    def get_quality_tests_for_state(self, state):
        self.ensure_quality_tests('create')
        self.ensure_quality_tests('state', state=state)
        template_ids = self.get_quality_test_template_ids(state)
        if not template_ids:
            return []
        return sorted([
                test for test in self.quality_tests
                if (test.state in {'draft', 'confirmed'}
                    and {template.id for template in test.templates}
                    & template_ids)
                ],
            key=lambda test: test.id)

    @classmethod
    def create(cls, vlist):
        works = super().create(vlist)
        for work in works:
            work.ensure_quality_tests('create')
        return works

    @classmethod
    @ModelView.button
    def start(cls, works):
        super().start(works)
        for work in works:
            work.ensure_quality_tests('state', state='running')

    @classmethod
    @ModelView.button
    def stop(cls, works):
        for work in works:
            work.ensure_quality_tests('state', state='done')
        super().stop(works)

    @classmethod
    def set_state(cls, works):
        previous_states = {
            work.id: work.state
            for work in works if getattr(work, 'id', None)
        }
        super().set_state(works)
        for work in works:
            if previous_states.get(work.id) != work.state:
                work.ensure_quality_tests('state', state=work.state)


class WorkShiftRecord(QualityRuleDocumentMixin, metaclass=PoolMeta):
    __name__ = 'production.work.shift.record'

    def get_quality_test_product(self):
        if self.work:
            return self.work.get_quality_test_product()
        if self.production and self.production.product:
            return self.production.product.template

    def get_quality_tests(self):
        return sorted([
                test for test in self.quality_tests
                if test.state in {'draft', 'confirmed'}
                ],
            key=lambda test: test.id)

    @classmethod
    def create(cls, vlist):
        records = super().create(vlist)
        for record in records:
            record.ensure_quality_tests('create')
            record.ensure_quality_tests('state', state=record.state)
        return records

    @classmethod
    def write(cls, *args):
        super().write(*args)
        records = sum(args[0::2], [])
        for record in records:
            record.ensure_quality_tests('state', state=record.state)


class WorkCycle(QualityRuleDocumentMixin, metaclass=PoolMeta):
    __name__ = 'production.work.cycle'

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
                'create_manual_quality_tests': {},
                })

    def get_quality_test_product(self):
        return self.work.get_quality_test_product()

    def get_quality_rule_operation(self):
        return self.work.operation

    def get_manual_quality_templates(self):
        return self.get_quality_templates('manual')

    def get_quality_tests(self):
        return sorted([
                test for test in self.quality_tests
                if test.state in {'draft', 'confirmed'}
                ],
            key=lambda test: test.id)

    def create_manual_tests(self, qualitative_map=None, quantitative_map=None,
            validate=True):
        return create_manual_quality_tests(
            self,
            self.get_manual_quality_templates(),
            company=self.company,
            qualitative_map=qualitative_map,
            quantitative_map=quantitative_map,
            test_date=self.create_date or datetime.now(),
            validate=validate)

    def save_quality_tests_from_values(self, qualitative_map=None,
            quantitative_map=None, validate_success_only=True):
        return apply_quality_test_values(
            self.get_quality_tests(),
            qualitative_map=qualitative_map,
            quantitative_map=quantitative_map,
            validate_success_only=validate_success_only)

    @classmethod
    def create(cls, vlist):
        cycles = super().create(vlist)
        for cycle in cycles:
            cycle.ensure_quality_tests('create')
        return cycles

    @classmethod
    @ModelView.button
    def create_manual_quality_tests(cls, cycles):
        for cycle in cycles:
            cycle.create_manual_tests(validate=False)

    @classmethod
    def run(cls, cycles):
        super().run(cycles)
        for cycle in cycles:
            cycle.ensure_quality_tests('state', state='running')

    @classmethod
    def do(cls, cycles):
        super().do(cycles)
        for cycle in cycles:
            cycle.ensure_quality_tests('state', state='done')


class CreateWorkShiftRecord(metaclass=PoolMeta):
    __name__ = 'production.work.shift.record.create'

    @classmethod
    def create_shift_record(cls, values):
        QualityControlRule = Pool().get('quality.control.rule')
        shift_record = super().create_shift_record(values)
        with Transaction().set_context(**_get_company_context(shift_record)):
            QualityControlRule.create_quality_tests(
                shift_record,
                document_model='production.work',
                trigger_document_model='production.work',
                creation_moment='create',
                company=shift_record.company,
                operation=shift_record.operation,
                product=shift_record.get_quality_test_product())
        return shift_record


def register():
    Pool.register(
        Work,
        WorkShiftRecord,
        WorkCycle,
        module='quality_control_rules_production', type_='model')
    Pool.register(
        CreateWorkShiftRecord,
        module='quality_control_rules_production', type_='wizard')
