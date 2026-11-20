from dataclasses import asdict

from .entries import Daybook, SignReceipt


def render_daybook(book: Daybook, receipt: SignReceipt) -> dict:
    result = book.result
    detail = {
        'book_id': book.book_id,
        'delivery': asdict(result.delivery),
        'intake_receipt_id': result.intake_receipt_id,
        'source': result.source,
        'specimens': [asdict(specimen) for specimen in result.specimens],
        'incoming_order': list(result.original_order),
        'processing_order': list(result.order),
        'profile': {
            'name': result.profile.name,
            'capacity_um': result.profile.capacity_um,
            'allowed_groups': list(result.profile.allowed_groups),
        },
        'loads': [
            {'group': load.group, 'members': list(load.members), 'total_um': load.total_um}
            for load in result.plan.loads
        ],
        'load_count': result.plan.load_count,
        'changeover_count': result.plan.changeover_count,
        'sign_receipt': asdict(receipt),
    }
    review = result.layout_review
    if review is not None:
        detail['layout_review'] = {
            'start_revision': review.start_revision,
            'end_revision': review.end_revision,
            'results': [
                {'note': dict(note), 'status': adjudication['status'],
                 'final_cut': adjudication['final_cut']}
                for note, adjudication in zip(review.notes, review.adjudications)
            ],
        }
    return detail
