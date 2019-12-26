import detect
import prepare
import eval as evaluation
from utils import env

if __name__ == '__main__':
    args = env.get_args()
    if args.job == 'prepare':
        prepare.prepare_luna()
    elif args.job == 'train':
        detect.run_train()
    elif args.job == 'test':
        detect.run_test()
    elif args.job == 'val':
        detect.run_validate()
    elif args.job == 'eval':
        evaluation.run_evaluation()
    else:
        raise ValueError('Not supported job name [%s]' % args.job)
