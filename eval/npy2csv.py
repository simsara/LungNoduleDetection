import csv
import os
from concurrent.futures import Future

import numpy as np

from evaluation.tools import VoxelToWorldCoord, load_itk_image, nms
from utils import file
from utils.log import get_logger
from utils.threadpool import pool

log = get_logger(__name__)

first_line = ['uid', 'coordX', 'coordY', 'coordZ', 'probability']
resolution = np.array([1, 1, 1])  # 分辨率 TODO 怎么跟网络保持一致
nms_thresh = 0.1  # 非极大值抑制的阈值设置


def convertcsv(bbox_name, bbox_path, detp):  # 给定pbb.npy的文件名，路径，阈值
    """
    对输出结节应用阈值和nms，输出的结果再转换为label一样的坐标体系，存在一个csv文件中
    """
    uid = bbox_name[:-8]
    mhd_file_name = file.get_mhd_file_path_name(uid)
    origin_file_name = file.get_origin_file_path_name(uid)
    space_file_name = file.get_space_file_path_name(uid)
    extend_file_name = file.get_extend_file_path_name(uid)
    sliceim, origin, spacing, is_flip = load_itk_image(mhd_file_name)  # 得到对应subset的原始数据
    origin = np.load(origin_file_name, mmap_mode='r')  # 得到对应subset预处理后的坐标原点
    spacing = np.load(space_file_name, mmap_mode='r')  # 体素间隙
    extendbox = np.load(extend_file_name, mmap_mode='r')  # 肺实质的拓展box
    pbb = np.load(os.path.join(bbox_path, bbox_name), mmap_mode='r')  # pbb.npy文件

    log.info('[%s] origin pbb. Shape: %s. Max: %3.2f. Min: %3.2f' %
             (uid, pbb.shape, max(pbb[:, 0]), min(pbb[:, 0])))

    pbbold = np.array(pbb[pbb[:, 0] > detp])  # 根据阈值过滤掉概率低的
    pbbold = np.array(pbbold[pbbold[:, -1] > 3])  # add new 9 15 根据半径过滤掉小于3mm的
    log.info('[%s] pbb after >3. Shape: %s. Max: %3.2f. Min: %3.2f' %
             (uid, pbbold.shape, max(pbbold[:, 0]), min(pbbold[:, 0])))

    # pbbold = pbbold[np.argsort(-pbbold[:, 0])][:10000]  # 取概率值前1000的结节，不然直接进行nms太耗时
    # print("after sort bboxs : ",len(pbbold))
    pbb = nms(pbbold, nms_thresh)  # 对输出的结节进行nms
    # print("after nms bboxs : ", len(pbb))
    # print(bboxfname, pbbold.shape, pbb.shape, pbbold.shape)
    pbb = np.array(pbb[:, :-1])  # 去掉直径
    # print pbb[:, 0]

    # 对输出加上拓展box的坐标，其实就是恢复为原来的坐标
    pbb[:, 1:] = np.array(pbb[:, 1:] + np.expand_dims(extendbox[:, 0], 1).T)  # TODO
    # 将输出恢复为原来的分辨率，这样就对应了原始数据中的体素坐标
    pbb[:, 1:] = np.array(pbb[:, 1:] * np.expand_dims(resolution, 1).T / np.expand_dims(spacing, 1).T)  # TODO

    if is_flip:  # 如果有翻转，将坐标翻转回去
        mask_file_name = file.get_mask_file_path_name(uid)
        Mask = np.load(mask_file_name, mmap_mode='r')  # 得到对应subset的mask
        pbb[:, 2] = Mask.shape[1] - pbb[:, 2]
        pbb[:, 3] = Mask.shape[2] - pbb[:, 3]
    pos = VoxelToWorldCoord(pbb[:, 1:], origin, spacing)  # 将输出转化为世界坐标
    log.info('[%s] voxel to world finished. Shape: %s' % (uid, pos.shape))

    row_list = []
    for nk in range(pos.shape[0]):  # 每一个结节：文件名，z,y,x，是结节的概率(经过sigmoid处理)
        row_list.append([uid, pos[nk, 2], pos[nk, 1], pos[nk, 0], 1 / (1 + np.exp(-pbb[nk, 0]))])
    log.info('[%s] Done' % uid)
    return row_list


def get_csv(detp, eps, args):  # 给定阈值
    """
    对输出的结果文件调用convert_csv函数处理
    每一个epoch生成一个csv文件，存放80多个测试病例的预测结节位置及概率
    """
    for ep in eps:  # 对每一个epoch
        bbox_path = file.get_net_bbox_save_path(args)
        log.info('bbox path: %s' % bbox_path)
        for detp_thresh in detp:
            save_file_name = file.get_predanno_file_name(args, detp_thresh)
            log.info('ep: %d. detp: %3.2f. file: %s' % (ep, detp_thresh, save_file_name))
            f = open(save_file_name, 'w')
            file_writer = csv.writer(f)
            file_writer.writerow(first_line)  # 写入的第一行为 用户id 结节坐标x,y,z 结节概率
            pbb_list = []
            for file_name in os.listdir(bbox_path):  # bboxpath目录下的所有文件和文件夹
                if file_name.endswith('_pbb.npy'):  # 找到以_pbb.npy结尾的文件(结节概率文件)，添加进文件列表
                    pbb_list.append(file_name)
            log.info('Pbb size: %d' % len(pbb_list))

            future_list = []
            for pbb_file_name in pbb_list:
                future_list.add(pool.submit(convertcsv, bbox_name=pbb_file_name, bbox_path=bbox_path, detp=detp_thresh))

            for future in future_list:  # type: Future
                predanno = future.result()
                for row in predanno:
                    file_writer.writerow(row)

            f.close()
            log.info('Finished ep: %d. detp: %3.2f' % (ep, detp_thresh))
